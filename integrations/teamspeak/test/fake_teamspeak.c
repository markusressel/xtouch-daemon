// A TeamSpeak 3 client for the tests of the plugin (tests/voip/test_teamspeak_plugin.py): loads the plugin like
// TeamSpeak does, gives it the functions of made-up servers, and calls its callbacks as a script on stdin says, one
// command per line (SCH is a server tab, a server connection handler):
//
//   connect SCH LOCAL CHANNEL  the tab SCH is connected, its own client LOCAL in CHANNEL (the first tab is shown)
//   tab SCH                    the user switches to the tab SCH
//   user SCH ID CHANNEL NAME   a client comes, or moves to another channel
//   query SCH ID CHANNEL NAME  a ServerQuery client comes
//   leave SCH ID               a client leaves the server (still listed while the callback runs)
//   rename SCH ID NAME         a client changes their nickname
//   talk SCH ID STATUS         a talk status (0 not talking, 1 talking)
//   audio SCH ID VALUE         10 ms of the voice of ID with every sample VALUE (-1..1): prints "audio SAMPLE" after
//                              the plugin had it, or "audio muted" for a muted client, whose voice the server does
//                              not send
//   localmute SCH ID 0|1       the user mutes or unmutes ID in TeamSpeak's window (no callback, as in TeamSpeak)
//   localvolume SCH ID DB      the user changes the volume modifier of ID in TeamSpeak's window (no callback)
//   refuse SCH ID              the mute and the volume of ID fail from now on
//   slow MILLISECONDS          the mute and the volume take that long from now on
//   record                     prints what happened since the last `record`: "mute SCH ID RESULT", "unmute SCH ID
//                              RESULT", "volume SCH ID DB RESULT" (RESULT 0 for ok, else the error code),
//                              "log LEVEL CHANNEL MESSAGE"
//   disconnect SCH             the tab SCH disconnects
//   shutdown                   shuts the plugin down (prints "shutdown MILLISECONDS"); its functions are invalid then
//   quit                       shuts the plugin down if it still runs, and ends
//
// It answers every command with "ok" once the plugin returned.
//
// Threads: the callbacks run in the main thread, which runs the script. A call of a function of TeamSpeak in the
// main thread (in a callback, or in ts3plugin_init), and any call after ts3plugin_shutdown, aborts the fake, so the
// tests see it: the plugin makes them in a thread of its own.
#define _GNU_SOURCE
// the headers of the SDK need size_t and the fixed-size integers
#include <stddef.h>
#include <stdint.h>

#include "teamspeak/public_definitions.h"
#include "teamspeak/public_errors.h"
#include "teamspeak/public_rare_definitions.h"
#include "ts3_functions.h"

#include <dlfcn.h>
#include <math.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <time.h>
#include <unistd.h>

#define MAX_TABS 8
#define MAX_CLIENTS 64

struct client {
	uint64 tab;
	anyID id;
	uint64 channel;
	char name[128];
	int type;
	bool muted;
	float modifier;
	bool refuse;
};

static pthread_mutex_t state_lock = PTHREAD_MUTEX_INITIALIZER;
static uint64 tabs[MAX_TABS];
static int status[MAX_TABS];
static anyID own[MAX_TABS];
static size_t tab_count;
static uint64 current_tab;
static struct client clients[MAX_CLIENTS];
static size_t client_count;
static long slow_ms;
static pthread_t main_thread;
// false once ts3plugin_shutdown returned
static bool valid = true;

static void check(const char *function) {
	if (!valid) {
		fprintf(stderr, "%s called after ts3plugin_shutdown\n", function);
		abort();
	}
	if (pthread_equal(pthread_self(), main_thread)) {
		fprintf(stderr, "%s called in TeamSpeak's thread\n", function);
		abort();
	}
}

// with `state_lock` held
static size_t tab_index(uint64 tab) {
	for (size_t i = 0; i < tab_count; i++) {
		if (tabs[i] == tab) {
			return i;
		}
	}
	return MAX_TABS;
}

static struct client *find(uint64 tab, anyID id) {
	for (size_t i = 0; i < client_count; i++) {
		if (clients[i].tab == tab && clients[i].id == id) {
			return &clients[i];
		}
	}
	return NULL;
}

static bool connected(uint64 tab) {
	size_t index = tab_index(tab);
	return index < MAX_TABS && status[index] == STATUS_CONNECTION_ESTABLISHED;
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

// -- the functions of TeamSpeak -------------------------------------------------------------------------------------

static unsigned int free_memory(void *pointer) {
	check("freeMemory");
	free(pointer);
	return ERROR_ok;
}

static unsigned int log_message(const char *message, enum LogLevel severity, const char *channel, uint64 tab) {
	check("logMessage");
	record("log %d %s %s", severity, channel, message);
	return ERROR_ok;
}

static unsigned int error_message(unsigned int error, char **text) {
	check("getErrorMessage");
	*text = strdup(error == ERROR_client_invalid_id ? "invalid clientID" : "some error");
	return ERROR_ok;
}

static uint64 current_connection(void) {
	check("getCurrentServerConnectionHandlerID");
	pthread_mutex_lock(&state_lock);
	uint64 tab = current_tab;
	pthread_mutex_unlock(&state_lock);
	return tab;
}

static unsigned int connection_list(uint64 **result) {
	check("getServerConnectionHandlerList");
	pthread_mutex_lock(&state_lock);
	uint64 *list = calloc(tab_count + 1, sizeof(uint64));
	memcpy(list, tabs, tab_count * sizeof(uint64));
	pthread_mutex_unlock(&state_lock);
	*result = list;
	return ERROR_ok;
}

static unsigned int connection_status(uint64 tab, int *result) {
	check("getConnectionStatus");
	pthread_mutex_lock(&state_lock);
	size_t index = tab_index(tab);
	unsigned int error = index < MAX_TABS ? ERROR_ok : ERROR_invalid_server_connection_handler_id;
	*result = index < MAX_TABS ? status[index] : STATUS_DISCONNECTED;
	pthread_mutex_unlock(&state_lock);
	return error;
}

static unsigned int client_id(uint64 tab, anyID *result) {
	check("getClientID");
	pthread_mutex_lock(&state_lock);
	unsigned int error = connected(tab) ? ERROR_ok : ERROR_not_connected;
	*result = connected(tab) ? own[tab_index(tab)] : 0;
	pthread_mutex_unlock(&state_lock);
	return error;
}

static unsigned int channel_of_client(uint64 tab, anyID id, uint64 *result) {
	check("getChannelOfClient");
	pthread_mutex_lock(&state_lock);
	struct client *client = connected(tab) ? find(tab, id) : NULL;
	*result = client ? client->channel : 0;
	pthread_mutex_unlock(&state_lock);
	return client ? ERROR_ok : ERROR_client_invalid_id;
}

static unsigned int channel_client_list(uint64 tab, uint64 channel, anyID **result) {
	check("getChannelClientList");
	pthread_mutex_lock(&state_lock);
	anyID *list = calloc(MAX_CLIENTS + 1, sizeof(anyID));
	size_t count = 0;
	for (size_t i = 0; i < client_count && connected(tab); i++) {
		if (clients[i].tab == tab && clients[i].channel == channel) {
			list[count++] = clients[i].id;
		}
	}
	unsigned int error = connected(tab) ? ERROR_ok : ERROR_not_connected;
	pthread_mutex_unlock(&state_lock);
	*result = list;
	return error;
}

static unsigned int channel_string(uint64 tab, uint64 channel, size_t flag, char **result) {
	check("getChannelVariableAsString");
	if (flag != CHANNEL_NAME) {
		return ERROR_parameter_invalid;
	}
	char *text = malloc(32);
	snprintf(text, 32, "Channel %llu", (unsigned long long) channel);
	*result = text;
	return ERROR_ok;
}

static unsigned int client_string(uint64 tab, anyID id, size_t flag, char **result) {
	check("getClientVariableAsString");
	pthread_mutex_lock(&state_lock);
	struct client *client = connected(tab) ? find(tab, id) : NULL;
	unsigned int error = client == NULL ? ERROR_client_invalid_id : flag != CLIENT_NICKNAME ? ERROR_parameter_invalid : ERROR_ok;
	if (error == ERROR_ok) {
		*result = strdup(client->name);
	}
	pthread_mutex_unlock(&state_lock);
	return error;
}

static unsigned int client_int(uint64 tab, anyID id, size_t flag, int *result) {
	check("getClientVariableAsInt");
	pthread_mutex_lock(&state_lock);
	struct client *client = connected(tab) ? find(tab, id) : NULL;
	unsigned int error = client == NULL ? ERROR_client_invalid_id : ERROR_ok;
	if (client != NULL && flag == CLIENT_IS_MUTED) {
		*result = client->muted;
	} else if (client != NULL && flag == CLIENT_VOLUME_MODIFICATOR) {
		// in whole dB, as the header says it is an integer
		*result = (int) lroundf(client->modifier);
	} else if (client != NULL && flag == CLIENT_TYPE) {
		*result = client->type;
	} else if (client != NULL) {
		error = ERROR_parameter_invalid;
	}
	pthread_mutex_unlock(&state_lock);
	return error;
}

static void wait_slow(void) {
	pthread_mutex_lock(&state_lock);
	long milliseconds = slow_ms;
	pthread_mutex_unlock(&state_lock);
	if (milliseconds > 0) {
		struct timespec time = {milliseconds / 1000, (milliseconds % 1000) * 1000000L};
		nanosleep(&time, NULL);
	}
}

static unsigned int set_mute(uint64 tab, const anyID *ids, bool muted) {
	wait_slow();
	pthread_mutex_lock(&state_lock);
	unsigned int error = ERROR_ok;
	for (const anyID *id = ids; *id != 0; id++) {
		struct client *client = connected(tab) ? find(tab, *id) : NULL;
		unsigned int result = client == NULL || client->refuse ? ERROR_client_invalid_id : ERROR_ok;
		if (result == ERROR_ok) {
			client->muted = muted;
		}
		record("%s %llu %u %u", muted ? "mute" : "unmute", (unsigned long long) tab, *id, result);
		error = result != ERROR_ok ? result : error;
	}
	pthread_mutex_unlock(&state_lock);
	return error;
}

static unsigned int mute_clients(uint64 tab, const anyID *ids, const char *return_code) {
	check("requestMuteClients");
	return set_mute(tab, ids, true);
}

static unsigned int unmute_clients(uint64 tab, const anyID *ids, const char *return_code) {
	check("requestUnmuteClients");
	return set_mute(tab, ids, false);
}

static unsigned int volume_modifier(uint64 tab, anyID id, float value) {
	check("setClientVolumeModifier");
	wait_slow();
	pthread_mutex_lock(&state_lock);
	struct client *client = connected(tab) ? find(tab, id) : NULL;
	unsigned int result = client == NULL || client->refuse ? ERROR_client_invalid_id : ERROR_ok;
	if (result == ERROR_ok) {
		client->modifier = value;
	}
	record("volume %llu %u %.2f %u", (unsigned long long) tab, id, value, result);
	pthread_mutex_unlock(&state_lock);
	return result;
}

// -- the plugin -----------------------------------------------------------------------------------------------------

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

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s PLUGIN.so\n", argv[0]);
		return 2;
	}
	main_thread = pthread_self();
	void *plugin = dlopen(argv[1], RTLD_NOW | RTLD_LOCAL);
	if (plugin == NULL) {
		fprintf(stderr, "%s\n", dlerror());
		return 2;
	}
	const char *(*name)(void) = symbol(plugin, "ts3plugin_name");
	const char *(*version)(void) = symbol(plugin, "ts3plugin_version");
	int (*api_version)(void) = symbol(plugin, "ts3plugin_apiVersion");
	symbol(plugin, "ts3plugin_author");
	symbol(plugin, "ts3plugin_description");
	void (*set_functions)(const struct TS3Functions) = symbol(plugin, "ts3plugin_setFunctionPointers");
	int (*init)(void) = symbol(plugin, "ts3plugin_init");
	void (*shutdown)(void) = symbol(plugin, "ts3plugin_shutdown");
	void (*tab_changed)(uint64) = symbol(plugin, "ts3plugin_currentServerConnectionChanged");
	void (*connect_event)(uint64, int, unsigned int) = symbol(plugin, "ts3plugin_onConnectStatusChangeEvent");
	void (*move_event)(uint64, anyID, uint64, uint64, int, const char *) =
		symbol(plugin, "ts3plugin_onClientMoveEvent");
	void (*update_event)(uint64, anyID, anyID, const char *, const char *) =
		symbol(plugin, "ts3plugin_onUpdateClientEvent");
	void (*talk_event)(uint64, int, int, anyID) = symbol(plugin, "ts3plugin_onTalkStatusChangeEvent");
	void (*voice_event)(uint64, anyID, short *, int, int) = symbol(plugin, "ts3plugin_onEditPlaybackVoiceDataEvent");

	printf("plugin %s %s api %d\n", name(), version(), api_version());

	struct TS3Functions functions;
	// a function the fake does not have is NULL: calling it crashes the fake, which the tests see
	memset(&functions, 0, sizeof(functions));
	functions.freeMemory = free_memory;
	functions.logMessage = log_message;
	functions.getErrorMessage = error_message;
	functions.getCurrentServerConnectionHandlerID = current_connection;
	functions.getServerConnectionHandlerList = connection_list;
	functions.getConnectionStatus = connection_status;
	functions.getClientID = client_id;
	functions.getChannelOfClient = channel_of_client;
	functions.getChannelClientList = channel_client_list;
	functions.getChannelVariableAsString = channel_string;
	functions.getClientVariableAsString = client_string;
	functions.getClientVariableAsInt = client_int;
	functions.requestMuteClients = mute_clients;
	functions.requestUnmuteClients = unmute_clients;
	functions.setClientVolumeModifier = volume_modifier;
	set_functions(functions);
	if (init() != 0) {
		fprintf(stderr, "init failed\n");
		return 1;
	}
	printf("ready\n");
	fflush(stdout);

	char line[256];
	while (fgets(line, sizeof(line), stdin) != NULL) {
		unsigned long long tab;
		unsigned id, local;
		unsigned long long channel;
		int value;
		float level;
		char text[128];
		if (sscanf(line, "connect %llu %u %llu", &tab, &local, &channel) == 3) {
			pthread_mutex_lock(&state_lock);
			size_t index = tab_index(tab);
			if (index == MAX_TABS && tab_count < MAX_TABS) {
				index = tab_count++;
				tabs[index] = tab;
			}
			if (current_tab == 0) {
				current_tab = tab;
			}
			status[index] = STATUS_CONNECTION_ESTABLISHED;
			own[index] = (anyID) local;
			if (find(tab, (anyID) local) == NULL && client_count < MAX_CLIENTS) {
				clients[client_count++] = (struct client) {.tab = tab, .id = (anyID) local, .channel = channel, .name = "me"};
			}
			pthread_mutex_unlock(&state_lock);
			connect_event(tab, STATUS_CONNECTION_ESTABLISHED, ERROR_ok);
		} else if (sscanf(line, "tab %llu", &tab) == 1) {
			pthread_mutex_lock(&state_lock);
			current_tab = tab;
			pthread_mutex_unlock(&state_lock);
			tab_changed(tab);
		} else if (sscanf(line, "user %llu %u %llu %127[^\n]", &tab, &id, &channel, text) == 4
				   || sscanf(line, "query %llu %u %llu %127[^\n]", &tab, &id, &channel, text) == 4) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			uint64 previous = client ? client->channel : 0;
			if (client == NULL && client_count < MAX_CLIENTS) {
				client = &clients[client_count++];
				*client = (struct client) {.tab = tab, .id = (anyID) id};
			}
			client->channel = channel;
			client->type = line[0] == 'q' ? ClientType_SERVERQUERY : ClientType_NORMAL;
			snprintf(client->name, sizeof(client->name), "%s", text);
			pthread_mutex_unlock(&state_lock);
			move_event(tab, (anyID) id, previous, channel, previous == 0 ? ENTER_VISIBILITY : RETAIN_VISIBILITY, "");
		} else if (sscanf(line, "leave %llu %u", &tab, &id) == 2) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			uint64 previous = client ? client->channel : 0;
			pthread_mutex_unlock(&state_lock);
			if (client != NULL) {
				move_event(tab, (anyID) id, previous, 0, LEAVE_VISIBILITY, "bye");
				// gone a moment later: the plugin may read the channel in between
				usleep(20000);
				pthread_mutex_lock(&state_lock);
				client = find(tab, (anyID) id);
				*client = clients[--client_count];
				pthread_mutex_unlock(&state_lock);
			}
		} else if (sscanf(line, "rename %llu %u %127[^\n]", &tab, &id, text) == 3) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			if (client != NULL) {
				snprintf(client->name, sizeof(client->name), "%s", text);
			}
			pthread_mutex_unlock(&state_lock);
			update_event(tab, (anyID) id, (anyID) id, text, "");
		} else if (sscanf(line, "talk %llu %u %d", &tab, &id, &value) == 3) {
			talk_event(tab, value, 0, (anyID) id);
		} else if (sscanf(line, "audio %llu %u %f", &tab, &id, &level) == 3) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			bool muted = client != NULL && client->muted;
			pthread_mutex_unlock(&state_lock);
			if (muted) {
				printf("audio muted\n");
			} else {
				short sample = (short) lroundf(level * 32767.0f);
				// 2 frames of 2 channels
				short samples[4] = {sample, (short) -sample, sample, sample};
				voice_event(tab, (anyID) id, samples, 2, 2);
				printf("audio %.3f\n", samples[0] / 32767.0);
			}
		} else if (sscanf(line, "localmute %llu %u %d", &tab, &id, &value) == 3) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			if (client != NULL) {
				client->muted = value != 0;
			}
			pthread_mutex_unlock(&state_lock);
		} else if (sscanf(line, "localvolume %llu %u %f", &tab, &id, &level) == 3) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			if (client != NULL) {
				client->modifier = level;
			}
			pthread_mutex_unlock(&state_lock);
		} else if (sscanf(line, "refuse %llu %u", &tab, &id) == 2) {
			pthread_mutex_lock(&state_lock);
			struct client *client = find(tab, (anyID) id);
			if (client != NULL) {
				client->refuse = true;
			}
			pthread_mutex_unlock(&state_lock);
		} else if (sscanf(line, "slow %d", &value) == 1) {
			pthread_mutex_lock(&state_lock);
			slow_ms = value;
			pthread_mutex_unlock(&state_lock);
		} else if (strncmp(line, "record", 6) == 0) {
			print_record();
		} else if (sscanf(line, "disconnect %llu", &tab) == 1) {
			pthread_mutex_lock(&state_lock);
			size_t index = tab_index(tab);
			if (index < MAX_TABS) {
				status[index] = STATUS_DISCONNECTED;
			}
			for (size_t i = 0; i < client_count;) {
				if (clients[i].tab == tab) {
					clients[i] = clients[--client_count];
				} else {
					i++;
				}
			}
			pthread_mutex_unlock(&state_lock);
			connect_event(tab, STATUS_DISCONNECTED, ERROR_ok);
		} else if (strncmp(line, "shutdown", 8) == 0 || strncmp(line, "quit", 4) == 0) {
			if (valid) {
				struct timespec start;
				clock_gettime(CLOCK_MONOTONIC, &start);
				shutdown();
				valid = false;
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
