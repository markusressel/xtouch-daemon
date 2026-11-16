// The Mumble plugin of xtouch-daemon: tells the daemon who is in the user's channel and who talks, and takes the
// volume and mute of each participant from the faders and Mute buttons of `voip` strips.
//
// It connects to the socket of the daemon's `bridge` VoIP provider ($XDG_RUNTIME_DIR/xtouch-daemon-voip.sock, or
// $XTOUCH_DAEMON_VOIP_SOCKET) and speaks its protocol, one JSON object per line (see docs/integrations/mumble.md and
// src/xtouch_daemon/voip/bridge.py). It connects again whenever the daemon was not there or went away.
//
// Threads: Mumble calls the event callbacks in its main thread (the server ones in another), the audio callback in
// its audio thread. The plugin's own thread does the socket. Only the callbacks call the Mumble API: an API call from
// the plugin's thread would wait for the main thread, which waits for that thread while the plugin shuts down. So
// the volume and the mute are the plugin's own (it scales the voice of the participant before Mumble mixes it), not
// Mumble's "Local volume adjustment" and "Local mute", which the API can't set (volume) or which would need such a
// call (mute).
//
// Copyright the xtouch-daemon authors, AGPL-3.0-or-later. MumblePlugin.h is Mumble's, BSD-3-Clause (see
// include/LICENSE.mumble).

// API 1.0 (Mumble 1.4 and later): the plugin needs nothing of the later ones
#define MUMBLE_PLUGIN_API_MAJOR_MACRO 1
#define MUMBLE_PLUGIN_API_MINOR_MACRO 0
#define MUMBLE_PLUGIN_API_PATCH_MACRO 0
#include "MumblePlugin.h"

#include <errno.h>
#include <math.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#ifndef XTD_PLUGIN_VERSION_MAJOR
#	define XTD_PLUGIN_VERSION_MAJOR 0
#	define XTD_PLUGIN_VERSION_MINOR 1
#	define XTD_PLUGIN_VERSION_PATCH 0
#endif

// The version of the bridge protocol the plugin speaks (see src/xtouch_daemon/voip/bridge.py).
#define PROTOCOL 1
#define MAX_PARTICIPANTS 256
#define MAX_NAME 256
#define VOLUME_LIMIT 200
// How often the plugin sends the levels while someone talks, and looks for commands.
#define TICK_MS 50
// How often it tries to connect while the daemon is not there.
#define RETRY_MS 2000

static MumbleAPI api;
static mumble_plugin_id_t own_id;

struct participant {
	mumble_userid_t id;
	char name[MAX_NAME];
	bool talking;
	bool muted;
	int volume;
	// the loudest sample since the state was sent last, 0..1
	float peak;
};

// Everything the threads share, under `lock`.
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct participant participants[MAX_PARTICIPANTS];
static size_t participant_count;
static char channel[MAX_NAME];
static bool dirty;

static pthread_t worker;
static atomic_bool running;
static bool worker_started;

// -- the participants ---------------------------------------------------------------------------------------------

// The participant with this id, or NULL; with `lock` held.
static struct participant *find(mumble_userid_t id) {
	for (size_t i = 0; i < participant_count; i++) {
		if (participants[i].id == id) {
			return &participants[i];
		}
	}
	return NULL;
}

static void copy_name(char *target, const char *name) {
	snprintf(target, MAX_NAME, "%s", name ? name : "");
}

// The users in the channel of the local user, without them; called in Mumble's main thread. The volume and mute of
// those who stay are kept.
static void refresh(void) {
	mumble_connection_t connection;
	bool synchronized = false;
	mumble_userid_t local;
	mumble_channelid_t channel_id;
	mumble_userid_t *users = NULL;
	size_t user_count = 0;
	if (api.getActiveServerConnection(own_id, &connection) != MUMBLE_STATUS_OK
		|| api.isConnectionSynchronized(own_id, connection, &synchronized) != MUMBLE_STATUS_OK || !synchronized) {
		// not (yet) connected: mumble_onServerSynchronized comes once it is
		return;
	}
	if (api.getLocalUserID(own_id, connection, &local) != MUMBLE_STATUS_OK
		|| api.getChannelOfUser(own_id, connection, local, &channel_id) != MUMBLE_STATUS_OK
		|| api.getUsersInChannel(own_id, connection, channel_id, &users, &user_count) != MUMBLE_STATUS_OK) {
		return;
	}
	const char *channel_name = NULL;
	if (api.getChannelName(own_id, connection, channel_id, &channel_name) != MUMBLE_STATUS_OK) {
		channel_name = NULL;
	}

	struct participant *next = calloc(MAX_PARTICIPANTS, sizeof(struct participant));
	size_t next_count = 0;
	for (size_t i = 0; i < user_count && next_count < MAX_PARTICIPANTS && next != NULL; i++) {
		if (users[i] == local) {
			continue;
		}
		const char *name = NULL;
		if (api.getUserName(own_id, connection, users[i], &name) != MUMBLE_STATUS_OK) {
			continue;
		}
		struct participant *entry = &next[next_count++];
		entry->id = users[i];
		copy_name(entry->name, name);
		entry->volume = 100;
		api.freeMemory(own_id, name);
	}
	api.freeMemory(own_id, users);

	pthread_mutex_lock(&lock);
	for (size_t i = 0; i < next_count && next != NULL; i++) {
		struct participant *known = find(next[i].id);
		if (known != NULL) {
			next[i].talking = known->talking;
			next[i].muted = known->muted;
			next[i].volume = known->volume;
			next[i].peak = known->peak;
		}
	}
	if (next != NULL) {
		memcpy(participants, next, next_count * sizeof(struct participant));
		participant_count = next_count;
	}
	copy_name(channel, channel_name);
	dirty = true;
	pthread_mutex_unlock(&lock);
	free(next);
	if (channel_name != NULL) {
		api.freeMemory(own_id, channel_name);
	}
}

static void clear(void) {
	pthread_mutex_lock(&lock);
	participant_count = 0;
	channel[0] = '\0';
	dirty = true;
	pthread_mutex_unlock(&lock);
}

static void forget(mumble_userid_t id) {
	pthread_mutex_lock(&lock);
	struct participant *gone = find(id);
	if (gone != NULL) {
		size_t index = (size_t) (gone - participants);
		memmove(gone, gone + 1, (participant_count - index - 1) * sizeof(struct participant));
		participant_count--;
		dirty = true;
	}
	pthread_mutex_unlock(&lock);
}

// -- the protocol -------------------------------------------------------------------------------------------------

struct buffer {
	char *data;
	size_t size;
	size_t capacity;
};

static void append(struct buffer *buffer, const char *text, size_t length) {
	if (buffer->data == NULL) {
		return;
	}
	if (buffer->size + length + 1 > buffer->capacity) {
		size_t capacity = (buffer->size + length + 1) * 2;
		char *data = realloc(buffer->data, capacity);
		if (data == NULL) {
			free(buffer->data);
			buffer->data = NULL;
			return;
		}
		buffer->data = data;
		buffer->capacity = capacity;
	}
	memcpy(buffer->data + buffer->size, text, length);
	buffer->size += length;
	buffer->data[buffer->size] = '\0';
}

static void appendf(struct buffer *buffer, const char *format, ...) {
	char text[128];
	va_list arguments;
	va_start(arguments, format);
	int length = vsnprintf(text, sizeof(text), format, arguments);
	va_end(arguments);
	if (length > 0) {
		append(buffer, text, (size_t) length < sizeof(text) ? (size_t) length : sizeof(text) - 1);
	}
}

// A JSON string, with quotes.
static void append_string(struct buffer *buffer, const char *text) {
	append(buffer, "\"", 1);
	for (const unsigned char *c = (const unsigned char *) text; *c; c++) {
		if (*c == '"' || *c == '\\') {
			char escaped[2] = {'\\', (char) *c};
			append(buffer, escaped, 2);
		} else if (*c < 0x20) {
			appendf(buffer, "\\u%04x", *c);
		} else {
			append(buffer, (const char *) c, 1);
		}
	}
	append(buffer, "\"", 1);
}

// The whole state as a line; the peaks start again. NULL without memory.
static char *state_line(bool *talking) {
	struct buffer line = {malloc(1024), 0, 1024};
	appendf(&line, "{\"protocol\":%d,\"client\":\"mumble\",\"capabilities\":[\"volume\",\"mute\",\"levels\"],", PROTOCOL);
	pthread_mutex_lock(&lock);
	append(&line, "\"channel\":", 10);
	append_string(&line, channel);
	append(&line, ",\"participants\":[", 17);
	*talking = false;
	for (size_t i = 0; i < participant_count; i++) {
		struct participant *each = &participants[i];
		appendf(&line, "%s{\"id\":\"%u\",\"name\":", i ? "," : "", each->id);
		append_string(&line, each->name);
		appendf(&line, ",\"talking\":%s,\"muted\":%s,\"volume\":%d,\"level\":%.3f}", each->talking ? "true" : "false",
				each->muted ? "true" : "false", each->volume, (double) each->peak);
		*talking = *talking || each->talking;
		each->peak = 0.0f;
	}
	dirty = false;
	pthread_mutex_unlock(&lock);
	append(&line, "]}\n", 3);
	return line.data;
}

// The value after `"key":` in a line of the daemon, NULL if it has none. The daemon writes its lines with
// json.dumps(..., separators=(",", ":")), the only lines this parses.
static const char *value_of(const char *line, const char *key) {
	char pattern[64];
	snprintf(pattern, sizeof(pattern), "\"%s\":", key);
	const char *found = strstr(line, pattern);
	return found ? found + strlen(pattern) : NULL;
}

// A command of the daemon: {"set_volume":{"id":"12","volume":80}} or {"set_muted":{"id":"12","muted":true}}.
// Anything else (e.g. its greeting, {"daemon":"xtouch-daemon","protocol":1}) is ignored.
static void handle(const char *line) {
	bool volume_command = strstr(line, "\"set_volume\":") != NULL;
	bool mute_command = strstr(line, "\"set_muted\":") != NULL;
	const char *id_text = value_of(line, "id");
	if ((!volume_command && !mute_command) || id_text == NULL || *id_text != '"') {
		return;
	}
	char *end;
	unsigned long id = strtoul(id_text + 1, &end, 10);
	if (end == id_text + 1 || *end != '"') {
		return;
	}
	pthread_mutex_lock(&lock);
	struct participant *target = find((mumble_userid_t) id);
	if (target != NULL) {
		if (volume_command) {
			const char *volume = value_of(line, "volume");
			if (volume != NULL) {
				long value = strtol(volume, NULL, 10);
				target->volume = value < 0 ? 0 : value > VOLUME_LIMIT ? VOLUME_LIMIT : (int) value;
				dirty = true;
			}
		} else {
			const char *muted = value_of(line, "muted");
			if (muted != NULL) {
				target->muted = strncmp(muted, "true", 4) == 0;
				dirty = true;
			}
		}
	}
	pthread_mutex_unlock(&lock);
}

// -- the connection to the daemon ---------------------------------------------------------------------------------

static void socket_path(char *path, size_t size) {
	const char *explicit_path = getenv("XTOUCH_DAEMON_VOIP_SOCKET");
	const char *runtime = getenv("XDG_RUNTIME_DIR");
	if (explicit_path != NULL && *explicit_path) {
		snprintf(path, size, "%s", explicit_path);
	} else if (runtime != NULL && *runtime) {
		snprintf(path, size, "%s/xtouch-daemon-voip.sock", runtime);
	} else {
		// like the daemon without $XDG_RUNTIME_DIR (instance.runtime_file())
		const char *temporary = getenv("TMPDIR");
		snprintf(path, size, "%s/xtouch-daemon-%u/xtouch-daemon-voip.sock",
				 temporary != NULL && *temporary ? temporary : "/tmp", (unsigned) getuid());
	}
}

static int connect_daemon(void) {
	struct sockaddr_un address = {.sun_family = AF_UNIX};
	socket_path(address.sun_path, sizeof(address.sun_path));
	int fd = socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC, 0);
	if (fd < 0) {
		return -1;
	}
	if (connect(fd, (struct sockaddr *) &address, sizeof(address)) != 0) {
		close(fd);
		return -1;
	}
	// a daemon that stops reading must not stop the plugin
	struct timeval timeout = {.tv_sec = 1};
	setsockopt(fd, SOL_SOCKET, SO_SNDTIMEO, &timeout, sizeof(timeout));
	return fd;
}

static bool send_all(int fd, const char *data) {
	size_t length = strlen(data);
	while (length > 0) {
		ssize_t sent = send(fd, data, length, MSG_NOSIGNAL);
		if (sent < 0 && errno == EINTR) {
			continue;
		}
		if (sent <= 0) {
			return false;
		}
		data += sent;
		length -= (size_t) sent;
	}
	return true;
}

static void sleep_ms(long milliseconds) {
	struct timespec time = {milliseconds / 1000, (milliseconds % 1000) * 1000000L};
	nanosleep(&time, NULL);
}

static void *work(void *unused) {
	(void) unused;
	int fd = -1;
	char received[4096];
	size_t received_size = 0;
	bool talking = false;
	while (atomic_load(&running)) {
		if (fd < 0) {
			fd = connect_daemon();
			if (fd < 0) {
				for (long waited = 0; waited < RETRY_MS && atomic_load(&running); waited += TICK_MS) {
					sleep_ms(TICK_MS);
				}
				continue;
			}
			received_size = 0;
			pthread_mutex_lock(&lock);
			dirty = true;
			pthread_mutex_unlock(&lock);
		}
		struct pollfd poll_fd = {.fd = fd, .events = POLLIN};
		int ready = poll(&poll_fd, 1, TICK_MS);
		bool lost = ready < 0 && errno != EINTR;
		if (ready > 0) {
			ssize_t count = recv(fd, received + received_size, sizeof(received) - received_size - 1, 0);
			if (count <= 0) {
				lost = true;
			} else {
				received_size += (size_t) count;
				received[received_size] = '\0';
				char *start = received;
				char *newline;
				while ((newline = strchr(start, '\n')) != NULL) {
					*newline = '\0';
					handle(start);
					start = newline + 1;
				}
				received_size = strlen(start);
				memmove(received, start, received_size + 1);
				if (received_size == sizeof(received) - 1) {
					// no line is that long: not the daemon
					received_size = 0;
				}
			}
		}
		pthread_mutex_lock(&lock);
		bool changed = dirty;
		pthread_mutex_unlock(&lock);
		if (!lost && (changed || talking)) {
			char *line = state_line(&talking);
			lost = line == NULL || !send_all(fd, line);
			free(line);
		}
		if (lost) {
			close(fd);
			fd = -1;
			// not at once: the daemon may have refused this plugin (another one is connected), or be restarting
			for (long waited = 0; waited < RETRY_MS && atomic_load(&running); waited += TICK_MS) {
				sleep_ms(TICK_MS);
			}
		}
	}
	if (fd >= 0) {
		close(fd);
	}
	return NULL;
}

// -- the plugin API -----------------------------------------------------------------------------------------------

mumble_error_t mumble_init(mumble_plugin_id_t id) {
	own_id = id;
	clear();
	atomic_store(&running, true);
	worker_started = pthread_create(&worker, NULL, work, NULL) == 0;
	if (!worker_started) {
		api.log(own_id, "xtouch-daemon: can't start the thread that talks to the daemon");
		return MUMBLE_EC_GENERIC_ERROR;
	}
	// already connected when the plugin is enabled
	refresh();
	return MUMBLE_STATUS_OK;
}

void mumble_shutdown(void) {
	atomic_store(&running, false);
	if (worker_started) {
		// it never waits for Mumble, so it ends within a tick
		pthread_join(worker, NULL);
		worker_started = false;
	}
}

struct MumbleStringWrapper mumble_getName(void) {
	static const char *name = "xtouch-daemon";
	return (struct MumbleStringWrapper) {name, strlen(name), false};
}

struct MumbleStringWrapper mumble_getAuthor(void) {
	static const char *author = "xtouch-daemon";
	return (struct MumbleStringWrapper) {author, strlen(author), false};
}

struct MumbleStringWrapper mumble_getDescription(void) {
	static const char *description =
		"Shows the people in your channel on the voip strips of a Behringer X-Touch Extender (xtouch-daemon): who "
		"talks, their volume on the fader, Mute to mute them.";
	return (struct MumbleStringWrapper) {description, strlen(description), false};
}

mumble_version_t mumble_getAPIVersion(void) {
	return MUMBLE_PLUGIN_API_VERSION;
}

mumble_version_t mumble_getVersion(void) {
	return (mumble_version_t) {XTD_PLUGIN_VERSION_MAJOR, XTD_PLUGIN_VERSION_MINOR, XTD_PLUGIN_VERSION_PATCH};
}

uint32_t mumble_getFeatures(void) {
	// it changes the audio of the participants
	return MUMBLE_FEATURE_AUDIO;
}

void mumble_registerAPIFunctions(void *api_struct) {
	api = *(MumbleAPI *) api_struct;
}

void mumble_releaseResource(const void *pointer) {
	// every string it gives Mumble is static
	(void) pointer;
}

void mumble_onServerSynchronized(mumble_connection_t connection) {
	(void) connection;
	refresh();
}

void mumble_onServerDisconnected(mumble_connection_t connection) {
	(void) connection;
	// another thread: no API calls
	clear();
}

void mumble_onChannelEntered(mumble_connection_t connection, mumble_userid_t user, mumble_channelid_t previous,
							 mumble_channelid_t next) {
	(void) connection, (void) user, (void) previous, (void) next;
	refresh();
}

void mumble_onChannelExited(mumble_connection_t connection, mumble_userid_t user, mumble_channelid_t left) {
	(void) connection, (void) left;
	refresh();
	// a user who leaves the server may still be in the channel while this is called
	forget(user);
}

void mumble_onUserTalkingStateChanged(mumble_connection_t connection, mumble_userid_t user,
									  mumble_talking_state_t state) {
	(void) connection;
	bool talking = state == MUMBLE_TS_TALKING || state == MUMBLE_TS_WHISPERING || state == MUMBLE_TS_SHOUTING;
	pthread_mutex_lock(&lock);
	struct participant *speaker = find(user);
	if (speaker != NULL && speaker->talking != talking) {
		speaker->talking = talking;
		dirty = true;
	}
	pthread_mutex_unlock(&lock);
}

bool mumble_onAudioSourceFetched(float *pcm, uint32_t sample_count, uint16_t channel_count, uint32_t sample_rate,
								 bool speech, mumble_userid_t user) {
	(void) sample_rate;
	if (!speech) {
		return false;
	}
	size_t samples = (size_t) sample_count * channel_count;
	pthread_mutex_lock(&lock);
	struct participant *speaker = find(user);
	float gain = speaker == NULL ? 1.0f : speaker->muted ? 0.0f : (float) speaker->volume / 100.0f;
	float peak = 0.0f;
	for (size_t i = 0; i < samples; i++) {
		if (gain != 1.0f) {
			pcm[i] *= gain;
		}
		float level = fabsf(pcm[i]);
		peak = level > peak ? level : peak;
	}
	if (speaker != NULL && peak > speaker->peak) {
		speaker->peak = peak > 1.0f ? 1.0f : peak;
	}
	pthread_mutex_unlock(&lock);
	return gain != 1.0f;
}
