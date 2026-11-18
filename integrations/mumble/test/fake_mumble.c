// A Mumble for the tests of the plugin (tests/voip/test_mumble_plugin.py): loads the plugin like Mumble does, gives it the
// Mumble API of a made-up server, and calls its callbacks as a script on stdin says, one command per line:
//
//   connect LOCAL CHANNEL      the local user LOCAL in CHANNEL, connected and synchronized
//   user ID CHANNEL NAME       a user comes, or moves to another channel
//   leave ID                   a user leaves the server
//   talk ID STATE              a talking state (0 passive, 1 talking, 2 whispering, 3 shouting, 4 talking but
//                              locally muted)
//   audio ID VALUE             a voice packet of ID with every sample VALUE: prints "audio MODIFIED SAMPLE", or
//                              "audio muted" for a locally muted user, whose audio Mumble does not fetch
//   localmute ID 0|1           the user sets the local mute of ID in Mumble's window (no callback, as in Mumble)
//   refuse ID                  requestLocalMute fails for ID from now on
//   pause, resume              the main thread stops and starts running the API calls of other threads
//   queued                     prints "queued FUNCTION ID MUTED" for each API call waiting for the main thread
//   record                     prints what happened since the last `record`: "requestLocalMute ID MUTED RESULT"
//                              (RESULT 0 for ok, else the error code, or "timeout"), "log MESSAGE"
//   disconnect                 the connection ends
//   shutdown                   shuts the plugin down (prints "shutdown MILLISECONDS"); the API is invalid then
//   quit                       shuts the plugin down if it still runs, and ends
//
// It answers every command with "ok" once the plugin returned.
//
// Threads, as in Mumble (src/mumble/API_v_1_x_x.cpp): an API function called from another thread runs in the main
// thread, which runs such calls while it waits for the next command (not while it runs one, nor while paused); the
// caller waits for it, at most 800 ms, then it fails with MUMBLE_EC_API_REQUEST_TIMEOUT and does not run. The plugin
// calls only isUserLocallyMuted, requestLocalMute and log from its threads; any other function off the main thread,
// and any call after mumble_shutdown, aborts the fake, so the tests see it.
#define _GNU_SOURCE
#define MUMBLE_PLUGIN_API_MAJOR_MACRO 1
#define MUMBLE_PLUGIN_API_MINOR_MACRO 0
#define MUMBLE_PLUGIN_API_PATCH_MACRO 0
#define MUMBLE_PLUGIN_NO_DEFAULT_FUNCTION_DEFINITIONS
#include "MumblePlugin.h"

#include <dlfcn.h>
#include <errno.h>
#include <fcntl.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAX_USERS 64
#define TIMEOUT_MS 800

struct user {
	mumble_userid_t id;
	mumble_channelid_t channel;
	char name[128];
	bool local_mute;
	bool refuse;
};

static struct user users[MAX_USERS];
static size_t user_count;
static bool connected;
static mumble_userid_t local_user;
static pthread_t main_thread;
// false once mumble_shutdown returned
static bool api_valid = true;

static struct user *find(mumble_userid_t id) {
	for (size_t i = 0; i < user_count; i++) {
		if (users[i].id == id) {
			return &users[i];
		}
	}
	return NULL;
}

static bool on_main(void) {
	return pthread_equal(pthread_self(), main_thread);
}

static void check(const char *function, bool other_threads) {
	if (!api_valid) {
		fprintf(stderr, "%s called after mumble_shutdown\n", function);
		abort();
	}
	if (!other_threads && !on_main()) {
		fprintf(stderr, "%s called off the main thread\n", function);
		abort();
	}
}

// -- what happened, for `record` ----------------------------------------------------------------------------------

static pthread_mutex_t record_lock = PTHREAD_MUTEX_INITIALIZER;
static char *record_text;
static size_t record_size;

static void record(const char *format, ...) {
	char line[512];
	va_list arguments;
	va_start(arguments, format);
	vsnprintf(line, sizeof(line), format, arguments);
	va_end(arguments);
	pthread_mutex_lock(&record_lock);
	size_t length = strlen(line);
	record_text = realloc(record_text, record_size + length + 2);
	memcpy(record_text + record_size, line, length);
	record_text[record_size + length] = '\n';
	record_size += length + 1;
	record_text[record_size] = '\0';
	pthread_mutex_unlock(&record_lock);
}

static void print_record(void) {
	pthread_mutex_lock(&record_lock);
	if (record_text != NULL) {
		fputs(record_text, stdout);
		free(record_text);
		record_text = NULL;
		record_size = 0;
	}
	pthread_mutex_unlock(&record_lock);
}

// -- API calls from other threads ---------------------------------------------------------------------------------

enum call_state { QUEUED, RUNNING, DONE };

struct call {
	const char *function;
	mumble_userid_t user;
	bool muted;
	bool *result_muted;
	const char *message;
	mumble_error_t result;
	enum call_state state;
	struct call *next;
};

static pthread_mutex_t calls_lock = PTHREAD_MUTEX_INITIALIZER;
static pthread_cond_t calls_done;
static struct call *queue;
static bool paused;
// written to wake the main thread
static int wake_pipe[2];

// Runs a call, in the main thread.
static mumble_error_t run(struct call *call) {
	if (strcmp(call->function, "log") == 0) {
		record("log %s", call->message);
		return MUMBLE_STATUS_OK;
	}
	if (!connected) {
		return MUMBLE_EC_CONNECTION_NOT_FOUND;
	}
	struct user *user = find(call->user);
	if (strcmp(call->function, "isUserLocallyMuted") == 0) {
		if (user == NULL) {
			return MUMBLE_EC_USER_NOT_FOUND;
		}
		*call->result_muted = user->local_mute;
		return MUMBLE_STATUS_OK;
	}
	// requestLocalMute
	mumble_error_t result = MUMBLE_STATUS_OK;
	if (call->user == local_user) {
		result = MUMBLE_EC_INVALID_MUTE_TARGET;
	} else if (user == NULL) {
		result = MUMBLE_EC_USER_NOT_FOUND;
	} else if (user->refuse) {
		result = MUMBLE_EC_GENERIC_ERROR;
	} else {
		user->local_mute = call->muted;
	}
	record("requestLocalMute %u %d %d", call->user, call->muted, result);
	return result;
}

// Runs a call in the main thread, from any thread, as Mumble's C_WRAPPER does.
static mumble_error_t marshal(struct call *call) {
	check(call->function, true);
	if (on_main()) {
		return run(call);
	}
	struct timespec deadline;
	clock_gettime(CLOCK_MONOTONIC, &deadline);
	deadline.tv_sec += TIMEOUT_MS / 1000;
	deadline.tv_nsec += (TIMEOUT_MS % 1000) * 1000000L;
	if (deadline.tv_nsec >= 1000000000L) {
		deadline.tv_sec++;
		deadline.tv_nsec -= 1000000000L;
	}
	pthread_mutex_lock(&calls_lock);
	call->state = QUEUED;
	call->next = NULL;
	struct call **tail = &queue;
	while (*tail != NULL) {
		tail = &(*tail)->next;
	}
	*tail = call;
	// a full pipe wakes the main thread as well
	ssize_t written = write(wake_pipe[1], "x", 1);
	(void) written;
	while (call->state != DONE) {
		int waited = pthread_cond_timedwait(&calls_done, &calls_lock, &deadline);
		if (waited == ETIMEDOUT && call->state == QUEUED) {
			// cancelled before it ran
			for (struct call **each = &queue; *each != NULL; each = &(*each)->next) {
				if (*each == call) {
					*each = call->next;
					break;
				}
			}
			if (strcmp(call->function, "requestLocalMute") == 0) {
				record("requestLocalMute %u %d timeout", call->user, call->muted);
			}
			pthread_mutex_unlock(&calls_lock);
			return MUMBLE_EC_API_REQUEST_TIMEOUT;
		}
	}
	pthread_mutex_unlock(&calls_lock);
	return call->result;
}

// Runs the calls of other threads, in the main thread.
static void serve(void) {
	char drained[64];
	while (read(wake_pipe[0], drained, sizeof(drained)) > 0) {
	}
	pthread_mutex_lock(&calls_lock);
	while (!paused && queue != NULL) {
		struct call *call = queue;
		queue = call->next;
		call->state = RUNNING;
		pthread_mutex_unlock(&calls_lock);
		mumble_error_t result = run(call);
		pthread_mutex_lock(&calls_lock);
		call->result = result;
		call->state = DONE;
		pthread_cond_broadcast(&calls_done);
	}
	pthread_mutex_unlock(&calls_lock);
}

// -- the API ------------------------------------------------------------------------------------------------------

static mumble_error_t free_memory(mumble_plugin_id_t caller, const void *pointer) {
	check("freeMemory", false);
	free((void *) pointer);
	return MUMBLE_STATUS_OK;
}

static mumble_error_t active_connection(mumble_plugin_id_t caller, mumble_connection_t *connection) {
	check("getActiveServerConnection", false);
	if (!connected) {
		return MUMBLE_EC_NO_ACTIVE_CONNECTION;
	}
	*connection = 1;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t synchronized(mumble_plugin_id_t caller, mumble_connection_t connection, bool *result) {
	check("isConnectionSynchronized", false);
	*result = connected;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t local_user_id(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t *id) {
	check("getLocalUserID", false);
	*id = local_user;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t user_name(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
								const char **name) {
	check("getUserName", false);
	struct user *user = find(id);
	if (user == NULL) {
		return MUMBLE_EC_USER_NOT_FOUND;
	}
	*name = strdup(user->name);
	return MUMBLE_STATUS_OK;
}

static mumble_error_t channel_name(mumble_plugin_id_t caller, mumble_connection_t connection,
								   mumble_channelid_t channel, const char **name) {
	check("getChannelName", false);
	char *text = malloc(32);
	snprintf(text, 32, "Channel %d", channel);
	*name = text;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t channel_of_user(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
									  mumble_channelid_t *channel) {
	check("getChannelOfUser", false);
	struct user *user = find(id);
	if (user == NULL) {
		return MUMBLE_EC_USER_NOT_FOUND;
	}
	*channel = user->channel;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t users_in_channel(mumble_plugin_id_t caller, mumble_connection_t connection,
									   mumble_channelid_t channel, mumble_userid_t **list, size_t *count) {
	check("getUsersInChannel", false);
	mumble_userid_t *result = malloc(sizeof(mumble_userid_t) * MAX_USERS);
	*count = 0;
	for (size_t i = 0; i < user_count; i++) {
		if (users[i].channel == channel) {
			result[(*count)++] = users[i].id;
		}
	}
	*list = result;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t locally_muted(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
									bool *muted) {
	struct call call = {.function = "isUserLocallyMuted", .user = id, .result_muted = muted};
	return marshal(&call);
}

static mumble_error_t local_mute(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
								 bool muted) {
	struct call call = {.function = "requestLocalMute", .user = id, .muted = muted};
	return marshal(&call);
}

static mumble_error_t log_message(mumble_plugin_id_t caller, const char *message) {
	struct call call = {.function = "log", .message = message};
	return marshal(&call);
}

static void *symbol(void *library, const char *name) {
	void *found = dlsym(library, name);
	if (found == NULL) {
		fprintf(stderr, "the plugin has no %s\n", name);
		exit(2);
	}
	return found;
}

static long milliseconds_since(const struct timespec *start) {
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	return (now.tv_sec - start->tv_sec) * 1000 + (now.tv_nsec - start->tv_nsec) / 1000000;
}

// The next line of stdin, waiting for it while running the calls of other threads; false at the end.
static bool next_line(char *line, size_t size) {
	static char buffer[4096];
	static size_t filled;
	while (true) {
		char *newline = memchr(buffer, '\n', filled);
		if (newline != NULL) {
			size_t length = (size_t) (newline - buffer) + 1;
			size_t copied = length < size ? length : size - 1;
			memcpy(line, buffer, copied);
			line[copied] = '\0';
			memmove(buffer, buffer + length, filled - length);
			filled -= length;
			return true;
		}
		struct pollfd fds[2] = {{.fd = 0, .events = POLLIN}, {.fd = wake_pipe[0], .events = POLLIN}};
		if (poll(fds, 2, -1) < 0) {
			if (errno == EINTR) {
				continue;
			}
			return false;
		}
		if (fds[1].revents) {
			serve();
		}
		if (fds[0].revents) {
			ssize_t count = read(0, buffer + filled, sizeof(buffer) - filled);
			if (count <= 0) {
				return false;
			}
			filled += (size_t) count;
		}
	}
}

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s PLUGIN.so\n", argv[0]);
		return 2;
	}
	main_thread = pthread_self();
	pthread_condattr_t attributes;
	pthread_condattr_init(&attributes);
	pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
	pthread_cond_init(&calls_done, &attributes);
	if (pipe2(wake_pipe, O_NONBLOCK | O_CLOEXEC) != 0) {
		return 2;
	}
	void *plugin = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
	if (plugin == NULL) {
		fprintf(stderr, "%s\n", dlerror());
		return 2;
	}
	mumble_version_t (*api_version)(void) = symbol(plugin, "mumble_getAPIVersion");
	void (*register_api)(void *) = symbol(plugin, "mumble_registerAPIFunctions");
	mumble_error_t (*init)(mumble_plugin_id_t) = symbol(plugin, "mumble_init");
	void (*shutdown)(void) = symbol(plugin, "mumble_shutdown");
	struct MumbleStringWrapper (*name)(void) = symbol(plugin, "mumble_getName");
	uint32_t (*features)(void) = symbol(plugin, "mumble_getFeatures");
	void (*synchronized_event)(mumble_connection_t) = symbol(plugin, "mumble_onServerSynchronized");
	void (*disconnected_event)(mumble_connection_t) = symbol(plugin, "mumble_onServerDisconnected");
	void (*entered_event)(mumble_connection_t, mumble_userid_t, mumble_channelid_t, mumble_channelid_t) =
		symbol(plugin, "mumble_onChannelEntered");
	void (*exited_event)(mumble_connection_t, mumble_userid_t, mumble_channelid_t) =
		symbol(plugin, "mumble_onChannelExited");
	void (*talking_event)(mumble_connection_t, mumble_userid_t, mumble_talking_state_t) =
		symbol(plugin, "mumble_onUserTalkingStateChanged");
	bool (*audio_event)(float *, uint32_t, uint16_t, uint32_t, bool, mumble_userid_t) =
		symbol(plugin, "mumble_onAudioSourceFetched");

	mumble_version_t version = api_version();
	struct MumbleStringWrapper plugin_name = name();
	printf("plugin %.*s api %d.%d.%d features %u\n", (int) plugin_name.size, plugin_name.data, version.major,
		   version.minor, version.patch, features());

	MumbleAPI api = {0};
	api.freeMemory = free_memory;
	api.getActiveServerConnection = active_connection;
	api.isConnectionSynchronized = synchronized;
	api.getLocalUserID = local_user_id;
	api.getUserName = user_name;
	api.getChannelName = channel_name;
	api.getChannelOfUser = channel_of_user;
	api.getUsersInChannel = users_in_channel;
	api.isUserLocallyMuted = locally_muted;
	api.requestLocalMute = local_mute;
	api.log = log_message;
	register_api(&api);
	if (init(7) != MUMBLE_STATUS_OK) {
		fprintf(stderr, "init failed\n");
		return 1;
	}
	printf("ready\n");
	fflush(stdout);

	char line[256];
	while (next_line(line, sizeof(line))) {
		unsigned id;
		int channel, state;
		float value;
		char text[128];
		if (sscanf(line, "connect %u %d", &id, &channel) == 2) {
			local_user = id;
			if (find(id) == NULL && user_count < MAX_USERS) {
				users[user_count++] = (struct user) {.id = id, .channel = channel, .name = "me"};
			}
			connected = true;
			synchronized_event(1);
		} else if (sscanf(line, "user %u %d %127[^\n]", &id, &channel, text) == 3) {
			struct user *user = find(id);
			mumble_channelid_t previous = user ? user->channel : -1;
			if (user == NULL && user_count < MAX_USERS) {
				user = &users[user_count++];
				*user = (struct user) {.id = id};
			}
			user->channel = channel;
			snprintf(user->name, sizeof(user->name), "%s", text);
			entered_event(1, id, previous, channel);
		} else if (sscanf(line, "leave %u", &id) == 1) {
			struct user *user = find(id);
			if (user != NULL) {
				// still listed while the callback runs, as in Mumble
				exited_event(1, id, user->channel);
				*user = users[--user_count];
			}
		} else if (sscanf(line, "talk %u %d", &id, &state) == 2) {
			talking_event(1, id, (mumble_talking_state_t) state);
		} else if (sscanf(line, "audio %u %f", &id, &value) == 2) {
			struct user *user = find(id);
			if (user != NULL && user->local_mute) {
				printf("audio muted\n");
			} else {
				float pcm[4] = {value, value, value, value};
				bool modified = audio_event(pcm, 2, 2, 48000, true, id);
				printf("audio %d %.3f\n", modified, pcm[0]);
			}
		} else if (sscanf(line, "localmute %u %d", &id, &state) == 2) {
			struct user *user = find(id);
			if (user != NULL) {
				user->local_mute = state != 0;
			}
		} else if (sscanf(line, "refuse %u", &id) == 1) {
			struct user *user = find(id);
			if (user != NULL) {
				user->refuse = true;
			}
		} else if (strncmp(line, "pause", 5) == 0 || strncmp(line, "resume", 6) == 0) {
			pthread_mutex_lock(&calls_lock);
			paused = line[0] == 'p';
			pthread_mutex_unlock(&calls_lock);
			serve();
		} else if (strncmp(line, "queued", 6) == 0) {
			pthread_mutex_lock(&calls_lock);
			for (struct call *call = queue; call != NULL; call = call->next) {
				printf("queued %s %u %d\n", call->function, call->user, call->muted);
			}
			pthread_mutex_unlock(&calls_lock);
		} else if (strncmp(line, "record", 6) == 0) {
			print_record();
		} else if (strncmp(line, "disconnect", 10) == 0) {
			connected = false;
			disconnected_event(1);
		} else if (strncmp(line, "shutdown", 8) == 0 || strncmp(line, "quit", 4) == 0) {
			if (api_valid) {
				struct timespec start;
				clock_gettime(CLOCK_MONOTONIC, &start);
				shutdown();
				api_valid = false;
				if (line[0] == 's') {
					printf("shutdown %ld\n", milliseconds_since(&start));
				}
			}
			if (line[0] == 'q') {
				printf("ok\n");
				fflush(stdout);
				break;
			}
		} else {
			printf("unknown %s", line);
		}
		printf("ok\n");
		fflush(stdout);
	}
	dlclose(plugin);
	return 0;
}
