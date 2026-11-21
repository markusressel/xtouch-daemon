// The TeamSpeak 3 plugin of xtouch-daemon: tells the daemon who is in the user's channel, who talks and whom the
// user muted, and takes the volume and mute of each participant from the faders and Mute buttons of `voip` strips.
//
// It connects to the socket of the daemon's `bridge` VoIP provider ($XDG_RUNTIME_DIR/xtouch-daemon-voip.sock, or
// $XTOUCH_DAEMON_VOIP_SOCKET) and speaks its protocol, one JSON object per line (see
// docs/reference/voice-chat-bridge.md and src/xtouch_daemon/voip/bridge.py). It connects again whenever the daemon
// was not there or went away. It works like the Mumble plugin (integrations/mumble/plugin.c).
//
// The server: the tab that is shown in TeamSpeak, if it is connected; else the first connected tab. Switching tabs
// switches the participants.
//
// The volume is TeamSpeak's own volume modifier of the participant (setClientVolumeModifier, in dB), the one of
// "Change Volume" in TeamSpeak's menu of a client: the plugin maps the percent of the protocol to it as a gain,
// dB = 20 * log10(percent / 100), so 100 % is 0 dB, 50 % is -6 dB and 200 % is +6 dB; 0 % is MIN_DB, and the plugin
// silences the voice itself then. A modifier changed in TeamSpeak moves the fader (read every POLL_MS).
//
// Mute is TeamSpeak's "Mute Client" (requestMuteClients, CLIENT_IS_MUTED): TeamSpeak shows it, and a mute set in
// TeamSpeak lights the Mute button. TeamSpeak has no event for a change of it, so the plugin reads it every POLL_MS.
//
// The levels come from onEditPlaybackVoiceDataEvent: the voice of a participant as it arrives, before TeamSpeak's
// volume modifier and its 3D positioning. That is `pre_fader_level`; `level` is it times the gain of the volume.
//
// Threads: TeamSpeak calls the callbacks in its own threads (the voice ones in its audio thread, every 10 ms while
// someone talks). They only take `lock` for a moment and make no calls into TeamSpeak. The plugin has two threads:
// - `work()` does the socket and never calls TeamSpeak. It queues the commands of the daemon.
// - `follow_teamspeak()` makes every call into TeamSpeak: it reads the channel when a callback says it changed, sets
//   the volumes and mutes the daemon asked for, and reads the mutes and volumes every POLL_MS.
// No thread holds `lock` during a call into TeamSpeak, so a callback never waits for one. ts3plugin_shutdown waits
// for both threads: `work()` ends within a tick, `follow_teamspeak()` after the call it makes, if any.
//
// Copyright the xtouch-daemon authors, AGPL-3.0-or-later. The headers of TeamSpeak's plugin SDK are not part of
// this repository: CMakeLists.txt downloads them (see there).

// the headers of the SDK need size_t and the fixed-size integers
#include <stddef.h>
#include <stdint.h>

#include "teamspeak/public_definitions.h"
#include "teamspeak/public_errors.h"
#include "teamspeak/public_rare_definitions.h"
#include "ts3_functions.h"

#include <errno.h>
#include <math.h>
#include <poll.h>
#include <pthread.h>
#include <stdarg.h>
#include <stdatomic.h>
#include <stdbool.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <time.h>
#include <unistd.h>

#define EXPORT __attribute__((visibility("default")))

#ifndef XTD_PLUGIN_VERSION
#	define XTD_PLUGIN_VERSION "0.0.0"
#endif

// The plugin API of TeamSpeak 3.6 (the client loads no other).
#define PLUGIN_API_VERSION 26
// The version of the bridge protocol the plugin speaks (see src/xtouch_daemon/voip/bridge.py).
#define PROTOCOL 1
#define MAX_PARTICIPANTS 256
#define MAX_NAME 256
#define VOLUME_LIMIT 200
// The volume modifier of 0 %: the quietest the plugin sets (it silences the voice itself).
#define MIN_DB (-60.0f)
// How far a modifier read from TeamSpeak may be from the one set (TeamSpeak tells it in whole dB) and still be it.
#define DB_TOLERANCE 1.0f
// How often the plugin sends the levels while someone talks, and looks for commands.
#define TICK_MS 50
// How often it tries to connect while the daemon is not there.
#define RETRY_MS 2000
// How often it reads the mutes and volume modifiers of TeamSpeak while the daemon is connected.
#define POLL_MS 500
// How long after a mute of the daemon it trusts it over what TeamSpeak tells (the server may take a moment).
#define SETTLE_MS 1500
#define LOG_CHANNEL "xtouch-daemon"

static struct TS3Functions ts;

struct participant {
	anyID id;
	char name[MAX_NAME];
	bool talking;
	// TeamSpeak's mute, as last read or set
	bool muted;
	// the mute the daemon asked for, until the request is made (`mute_requests` != `mute_done`)
	bool wanted;
	unsigned mute_requests;
	unsigned mute_done;
	// until then, a mute read from TeamSpeak does not replace the one set
	struct timespec settle;
	// the volume, in percent, and the volume modifier in TeamSpeak, as last read or set
	int volume;
	float modifier;
	// a volume of the daemon to set (`volume_requests` != `volume_done`)
	unsigned volume_requests;
	unsigned volume_done;
	// the loudest sample since the state was sent last, 0..1: after the volume, and before it
	float peak;
	float pre_fader_peak;
};

// Everything the threads share, under `lock`.
static pthread_mutex_t lock = PTHREAD_MUTEX_INITIALIZER;
static struct participant participants[MAX_PARTICIPANTS];
static size_t participant_count;
static char channel[MAX_NAME];
// the server tab and channel the participants are of, and the user's own client there (0: none)
static uint64 shown_connection;
static uint64 shown_channel;
static anyID own_client;
// clients who left the channel, which TeamSpeak may list in it for a moment after the callback
static anyID left[MAX_PARTICIPANTS];
static size_t left_count;
// the state changed since it was sent
static bool dirty;
// a callback said that the channel or its people changed: `follow_teamspeak()` reads them again
static bool stale;
// wakes `follow_teamspeak()`: a request, a change, or the shutdown
static pthread_cond_t wake;

static pthread_t worker;
static pthread_t teamspeak_thread;
static atomic_bool running;
static atomic_bool daemon_connected;
static bool worker_started;
static bool teamspeak_thread_started;

// -- time -----------------------------------------------------------------------------------------------------------

static struct timespec after_ms(long milliseconds) {
	struct timespec time;
	clock_gettime(CLOCK_MONOTONIC, &time);
	time.tv_sec += milliseconds / 1000;
	time.tv_nsec += (milliseconds % 1000) * 1000000L;
	if (time.tv_nsec >= 1000000000L) {
		time.tv_sec++;
		time.tv_nsec -= 1000000000L;
	}
	return time;
}

static bool reached(const struct timespec *time) {
	struct timespec now;
	clock_gettime(CLOCK_MONOTONIC, &now);
	return now.tv_sec > time->tv_sec || (now.tv_sec == time->tv_sec && now.tv_nsec >= time->tv_nsec);
}

static void sleep_ms(long milliseconds) {
	struct timespec time = {milliseconds / 1000, (milliseconds % 1000) * 1000000L};
	nanosleep(&time, NULL);
}

// -- the volume -----------------------------------------------------------------------------------------------------

static float modifier_of(int volume) {
	if (volume <= 0) {
		return MIN_DB;
	}
	float decibel = 20.0f * log10f((float) volume / 100.0f);
	return decibel < MIN_DB ? MIN_DB : decibel;
}

static int volume_of(float modifier) {
	if (modifier <= MIN_DB + 0.5f) {
		return 0;
	}
	long volume = lroundf(100.0f * powf(10.0f, modifier / 20.0f));
	return volume < 0 ? 0 : volume > VOLUME_LIMIT ? VOLUME_LIMIT : (int) volume;
}

// -- the participants ---------------------------------------------------------------------------------------------

// The participant with this id, or NULL; with `lock` held.
static struct participant *find(anyID id) {
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

// The mute the daemon sees: what it asked for while the request is under way.
static bool shown_muted(const struct participant *participant) {
	return participant->mute_requests != participant->mute_done ? participant->wanted : participant->muted;
}

// A participant with a request of the daemon that has not been made, or NULL; with `lock` held.
static struct participant *requested(void) {
	for (size_t i = 0; i < participant_count; i++) {
		if (participants[i].mute_requests != participants[i].mute_done
			|| participants[i].volume_requests != participants[i].volume_done) {
			return &participants[i];
		}
	}
	return NULL;
}

// Something changed in TeamSpeak: `follow_teamspeak()` reads the channel again. Any thread, without `lock`.
static void changed(void) {
	pthread_mutex_lock(&lock);
	stale = true;
	pthread_cond_signal(&wake);
	pthread_mutex_unlock(&lock);
}

// Whether a callback is about the server the participants are of; with `lock` held.
static bool shown(uint64 connection) {
	return connection != 0 && connection == shown_connection;
}

static bool connection_ready(uint64 connection) {
	int status = STATUS_DISCONNECTED;
	return connection != 0 && ts.getConnectionStatus(connection, &status) == ERROR_ok
		&& status == STATUS_CONNECTION_ESTABLISHED;
}

// The server tab to show: the current one if it is connected, else the first connected one, 0 for none.
static uint64 pick_connection(void) {
	uint64 current = ts.getCurrentServerConnectionHandlerID();
	if (connection_ready(current)) {
		return current;
	}
	uint64 *connections = NULL;
	uint64 found = 0;
	if (ts.getServerConnectionHandlerList(&connections) == ERROR_ok && connections != NULL) {
		for (size_t i = 0; connections[i] != 0 && found == 0; i++) {
			if (connection_ready(connections[i])) {
				found = connections[i];
			}
		}
		ts.freeMemory(connections);
	}
	return found;
}

// No participants; `connection` is the server they will be of, 0 for none.
static void clear(uint64 connection) {
	pthread_mutex_lock(&lock);
	participant_count = 0;
	left_count = 0;
	channel[0] = '\0';
	shown_connection = connection;
	shown_channel = 0;
	own_client = 0;
	dirty = true;
	pthread_mutex_unlock(&lock);
}

static bool has_left(anyID id);
static void set_left(anyID id, bool gone);

// Reads the clients in the user's channel, without the user and ServerQuery clients, with their mute and volume
// modifier; in `follow_teamspeak()`. The volume, the talking and the requests of those who stay are kept.
static void refresh(void) {
	uint64 connection = pick_connection();
	anyID own = 0;
	uint64 channel_id = 0;
	anyID *clients = NULL;
	if (connection == 0 || ts.getClientID(connection, &own) != ERROR_ok
		|| ts.getChannelOfClient(connection, own, &channel_id) != ERROR_ok
		|| ts.getChannelClientList(connection, channel_id, &clients) != ERROR_ok || clients == NULL) {
		// not (yet) connected: onConnectStatusChangeEvent comes once it is
		clear(0);
		return;
	}
	char *channel_name = NULL;
	if (ts.getChannelVariableAsString(connection, channel_id, CHANNEL_NAME, &channel_name) != ERROR_ok) {
		channel_name = NULL;
	}

	struct participant *next = calloc(MAX_PARTICIPANTS, sizeof(struct participant));
	// what could be read of next[i]
	bool read_mute[MAX_PARTICIPANTS] = {false};
	bool read_volume[MAX_PARTICIPANTS] = {false};
	size_t next_count = 0;
	for (size_t i = 0; clients[i] != 0 && next_count < MAX_PARTICIPANTS && next != NULL; i++) {
		int type = ClientType_NORMAL;
		if (clients[i] == own
			|| (ts.getClientVariableAsInt(connection, clients[i], CLIENT_TYPE, &type) == ERROR_ok
				&& type != ClientType_NORMAL)) {
			continue;
		}
		char *name = NULL;
		if (ts.getClientVariableAsString(connection, clients[i], CLIENT_NICKNAME, &name) != ERROR_ok) {
			continue;
		}
		struct participant *entry = &next[next_count];
		entry->id = clients[i];
		copy_name(entry->name, name);
		ts.freeMemory(name);
		int muted = 0;
		read_mute[next_count] =
			ts.getClientVariableAsInt(connection, clients[i], CLIENT_IS_MUTED, &muted) == ERROR_ok;
		entry->muted = muted != 0;
		int modifier = 0;
		read_volume[next_count] =
			ts.getClientVariableAsInt(connection, clients[i], CLIENT_VOLUME_MODIFICATOR, &modifier) == ERROR_ok;
		entry->modifier = read_volume[next_count] ? (float) modifier : 0.0f;
		entry->volume = volume_of(entry->modifier);
		next_count++;
	}
	ts.freeMemory(clients);

	pthread_mutex_lock(&lock);
	bool same = connection == shown_connection;
	if (!same) {
		left_count = 0;
	}
	// who left and is still listed stays out; who is no longer listed needs no more care
	size_t kept = 0;
	for (size_t i = 0; i < left_count; i++) {
		bool listed = false;
		for (size_t j = 0; j < next_count && next != NULL; j++) {
			listed = listed || next[j].id == left[i];
		}
		if (listed) {
			left[kept++] = left[i];
		}
	}
	left_count = kept;
	size_t staying = 0;
	for (size_t i = 0; i < next_count && next != NULL; i++) {
		if (!has_left(next[i].id)) {
			next[staying] = next[i];
			read_mute[staying] = read_mute[i];
			read_volume[staying] = read_volume[i];
			staying++;
		}
	}
	next_count = next != NULL ? staying : 0;
	for (size_t i = 0; i < next_count && next != NULL && same; i++) {
		struct participant *known = find(next[i].id);
		if (known == NULL) {
			continue;
		}
		struct participant *entry = &next[i];
		entry->talking = known->talking;
		if (!read_mute[i] || !reached(&known->settle)) {
			entry->muted = known->muted;
		}
		entry->wanted = known->wanted;
		entry->mute_requests = known->mute_requests;
		entry->mute_done = known->mute_done;
		entry->settle = known->settle;
		if (!read_volume[i] || fabsf(entry->modifier - known->modifier) < DB_TOLERANCE
			|| known->volume_requests != known->volume_done) {
			entry->modifier = known->modifier;
			entry->volume = known->volume;
		}
		entry->volume_requests = known->volume_requests;
		entry->volume_done = known->volume_done;
		entry->peak = known->peak;
		entry->pre_fader_peak = known->pre_fader_peak;
	}
	if (next != NULL) {
		memcpy(participants, next, next_count * sizeof(struct participant));
		participant_count = next_count;
	}
	copy_name(channel, channel_name);
	shown_connection = connection;
	shown_channel = channel_id;
	own_client = own;
	dirty = true;
	pthread_mutex_unlock(&lock);
	free(next);
	if (channel_name != NULL) {
		ts.freeMemory(channel_name);
	}
}

// Whether `id` left the channel and TeamSpeak may still list it; with `lock` held.
static bool has_left(anyID id) {
	for (size_t i = 0; i < left_count; i++) {
		if (left[i] == id) {
			return true;
		}
	}
	return false;
}

static void set_left(anyID id, bool gone) {
	for (size_t i = 0; i < left_count; i++) {
		if (left[i] == id) {
			left[i] = left[--left_count];
			break;
		}
	}
	if (gone && left_count < MAX_PARTICIPANTS) {
		left[left_count++] = id;
	}
}

// With `lock` held.
static void forget(anyID id) {
	set_left(id, true);
	struct participant *gone = find(id);
	if (gone != NULL) {
		size_t index = (size_t) (gone - participants);
		memmove(gone, gone + 1, (participant_count - index - 1) * sizeof(struct participant));
		participant_count--;
		dirty = true;
	}
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
	appendf(&line, "{\"protocol\":%d,\"client\":\"teamspeak\",\"capabilities\":[\"volume\",\"mute\",\"levels\"],",
			PROTOCOL);
	pthread_mutex_lock(&lock);
	append(&line, "\"channel\":", 10);
	append_string(&line, channel);
	append(&line, ",\"participants\":[", 17);
	*talking = false;
	for (size_t i = 0; i < participant_count; i++) {
		struct participant *each = &participants[i];
		appendf(&line, "%s{\"id\":\"%u\",\"name\":", i ? "," : "", (unsigned) each->id);
		append_string(&line, each->name);
		appendf(&line, ",\"talking\":%s,\"muted\":%s,\"volume\":%d,\"level\":%.3f,\"pre_fader_level\":%.3f}",
				each->talking ? "true" : "false", shown_muted(each) ? "true" : "false", each->volume, (double) each->peak,
				(double) each->pre_fader_peak);
		*talking = *talking || each->talking;
		each->peak = 0.0f;
		each->pre_fader_peak = 0.0f;
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
// Anything else (e.g. its greeting, {"daemon":"xtouch-daemon","protocol":1}) is ignored. Both are requests for
// `follow_teamspeak()`: this thread makes no calls into TeamSpeak.
static void handle(const char *line) {
	bool volume_command = strstr(line, "\"set_volume\":") != NULL;
	bool mute_command = strstr(line, "\"set_muted\":") != NULL;
	const char *id_text = value_of(line, "id");
	if ((!volume_command && !mute_command) || id_text == NULL || *id_text != '"') {
		return;
	}
	char *end;
	unsigned long id = strtoul(id_text + 1, &end, 10);
	if (end == id_text + 1 || *end != '"' || id == 0 || id > 0xffff) {
		return;
	}
	pthread_mutex_lock(&lock);
	struct participant *target = find((anyID) id);
	if (target != NULL) {
		if (volume_command) {
			const char *volume = value_of(line, "volume");
			if (volume != NULL) {
				long value = strtol(volume, NULL, 10);
				target->volume = value < 0 ? 0 : value > VOLUME_LIMIT ? VOLUME_LIMIT : (int) value;
				target->volume_requests++;
				dirty = true;
				pthread_cond_signal(&wake);
			}
		} else {
			const char *muted = value_of(line, "muted");
			if (muted != NULL) {
				target->wanted = strncmp(muted, "true", 4) == 0;
				target->mute_requests++;
				dirty = true;
				pthread_cond_signal(&wake);
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

static void wait_to_retry(void) {
	for (long waited = 0; waited < RETRY_MS && atomic_load(&running); waited += TICK_MS) {
		sleep_ms(TICK_MS);
	}
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
				wait_to_retry();
				continue;
			}
			received_size = 0;
			atomic_store(&daemon_connected, true);
			pthread_mutex_lock(&lock);
			dirty = true;
			pthread_cond_signal(&wake);
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
		bool changed_state = dirty;
		pthread_mutex_unlock(&lock);
		if (!lost && (changed_state || talking)) {
			char *line = state_line(&talking);
			lost = line == NULL || !send_all(fd, line);
			free(line);
		}
		if (lost) {
			close(fd);
			fd = -1;
			atomic_store(&daemon_connected, false);
			// not at once: the daemon may have refused this plugin (another one is connected), or be restarting
			wait_to_retry();
		}
	}
	if (fd >= 0) {
		close(fd);
	}
	return NULL;
}

// -- the calls into TeamSpeak ---------------------------------------------------------------------------------------

static void log_error(uint64 connection, const char *what, const char *name, unsigned int error) {
	char *text = NULL;
	char message[MAX_NAME + 200];
	bool described = ts.getErrorMessage(error, &text) == ERROR_ok && text != NULL;
	snprintf(message, sizeof(message), "xtouch-daemon: can't %s %s in TeamSpeak: %s", what, name,
			 described ? text : "error");
	if (described) {
		ts.freeMemory(text);
	}
	ts.logMessage(message, LogLevel_WARNING, LOG_CHANNEL, connection);
}

// Makes the requests of `target`; with `lock` held, which it lets go during the calls. On an error the daemon sees
// TeamSpeak's mute or volume again (the button or fader goes back), and TeamSpeak's log tells why.
static void request(struct participant *target) {
	anyID id = target->id;
	char name[MAX_NAME];
	copy_name(name, target->name);
	uint64 connection = shown_connection;
	bool mute = target->mute_requests != target->mute_done;
	bool wanted = target->wanted;
	unsigned number = mute ? target->mute_requests : target->volume_requests;
	int volume = target->volume;
	float modifier = modifier_of(volume);
	pthread_mutex_unlock(&lock);
	unsigned int result;
	if (mute) {
		anyID clients[2] = {id, 0};
		result = wanted ? ts.requestMuteClients(connection, clients, NULL)
						: ts.requestUnmuteClients(connection, clients, NULL);
	} else {
		result = ts.setClientVolumeModifier(connection, id, modifier);
	}
	pthread_mutex_lock(&lock);
	target = connection == shown_connection ? find(id) : NULL;
	if (target != NULL) {
		if (mute) {
			bool before = shown_muted(target);
			if (result == ERROR_ok) {
				target->muted = wanted;
				target->settle = after_ms(SETTLE_MS);
			}
			// a later request, if any, is still to be made
			target->mute_done = number;
			dirty = dirty || shown_muted(target) != before;
		} else {
			if (result == ERROR_ok) {
				target->modifier = modifier;
			} else if (target->volume_requests == number) {
				target->volume = volume_of(target->modifier);
				dirty = true;
			}
			target->volume_done = number;
		}
	}
	if (result != ERROR_ok && atomic_load(&running)) {
		pthread_mutex_unlock(&lock);
		log_error(connection, mute ? (wanted ? "mute" : "unmute") : "set the volume of", name, result);
		pthread_mutex_lock(&lock);
	}
}

// Reads the mute and volume modifier of every participant; with `lock` held, which it lets go during the calls.
// Stops at a request of the daemon or a change, which come first.
static void poll_teamspeak(void) {
	anyID ids[MAX_PARTICIPANTS];
	size_t count = participant_count;
	for (size_t i = 0; i < count; i++) {
		ids[i] = participants[i].id;
	}
	uint64 connection = shown_connection;
	for (size_t i = 0; i < count && atomic_load(&running) && !stale && requested() == NULL; i++) {
		int muted = 0;
		int modifier = 0;
		pthread_mutex_unlock(&lock);
		bool read_mute = ts.getClientVariableAsInt(connection, ids[i], CLIENT_IS_MUTED, &muted) == ERROR_ok;
		bool read_volume =
			ts.getClientVariableAsInt(connection, ids[i], CLIENT_VOLUME_MODIFICATOR, &modifier) == ERROR_ok;
		pthread_mutex_lock(&lock);
		struct participant *participant = connection == shown_connection ? find(ids[i]) : NULL;
		// an error: someone who just left, or a connection that just ended, which the callbacks catch up with
		if (participant == NULL) {
			continue;
		}
		if (read_mute && reached(&participant->settle) && participant->muted != (muted != 0)) {
			bool before = shown_muted(participant);
			participant->muted = muted != 0;
			dirty = dirty || shown_muted(participant) != before;
		}
		if (read_volume && participant->volume_requests == participant->volume_done
			&& fabsf((float) modifier - participant->modifier) >= DB_TOLERANCE) {
			// changed in TeamSpeak
			participant->modifier = (float) modifier;
			participant->volume = volume_of(participant->modifier);
			dirty = true;
		}
	}
}

// The thread that makes the calls into TeamSpeak (see the top of the file).
static void *follow_teamspeak(void *unused) {
	(void) unused;
	struct timespec next_poll = after_ms(0);
	pthread_mutex_lock(&lock);
	while (atomic_load(&running)) {
		if (stale) {
			stale = false;
			pthread_mutex_unlock(&lock);
			refresh();
			pthread_mutex_lock(&lock);
			continue;
		}
		struct participant *target = requested();
		if (target != NULL) {
			request(target);
			continue;
		}
		bool polling = atomic_load(&daemon_connected) && shown_connection != 0 && participant_count > 0;
		if (polling && reached(&next_poll)) {
			poll_teamspeak();
			next_poll = after_ms(POLL_MS);
			continue;
		}
		struct timespec until = polling ? next_poll : after_ms(POLL_MS);
		pthread_cond_timedwait(&wake, &lock, &until);
	}
	pthread_mutex_unlock(&lock);
	return NULL;
}

// -- the plugin API -----------------------------------------------------------------------------------------------

static void stop(void) {
	atomic_store(&running, false);
	pthread_mutex_lock(&lock);
	pthread_cond_broadcast(&wake);
	pthread_mutex_unlock(&lock);
	if (worker_started) {
		// it never waits for TeamSpeak, so it ends within a tick
		pthread_join(worker, NULL);
		worker_started = false;
	}
	if (teamspeak_thread_started) {
		// at most after the call into TeamSpeak it makes
		pthread_join(teamspeak_thread, NULL);
		teamspeak_thread_started = false;
	}
	pthread_cond_destroy(&wake);
}

EXPORT const char *ts3plugin_name(void) {
	return "xtouch-daemon";
}

EXPORT const char *ts3plugin_version(void) {
	return XTD_PLUGIN_VERSION;
}

EXPORT int ts3plugin_apiVersion(void) {
	return PLUGIN_API_VERSION;
}

EXPORT const char *ts3plugin_author(void) {
	return "xtouch-daemon";
}

EXPORT const char *ts3plugin_description(void) {
	return "Shows the people in your channel on the voip strips of a Behringer X-Touch Extender (xtouch-daemon): who "
		   "talks, their volume on the fader, Mute for TeamSpeak's Mute Client.";
}

EXPORT void ts3plugin_setFunctionPointers(const struct TS3Functions functions) {
	ts = functions;
}

EXPORT int ts3plugin_init(void) {
	pthread_mutex_lock(&lock);
	participant_count = 0;
	left_count = 0;
	channel[0] = '\0';
	shown_connection = 0;
	shown_channel = 0;
	own_client = 0;
	dirty = true;
	// already connected when the plugin is enabled
	stale = true;
	pthread_mutex_unlock(&lock);
	pthread_condattr_t attributes;
	pthread_condattr_init(&attributes);
	pthread_condattr_setclock(&attributes, CLOCK_MONOTONIC);
	pthread_cond_init(&wake, &attributes);
	pthread_condattr_destroy(&attributes);
	atomic_store(&daemon_connected, false);
	atomic_store(&running, true);
	worker_started = pthread_create(&worker, NULL, work, NULL) == 0;
	teamspeak_thread_started = pthread_create(&teamspeak_thread, NULL, follow_teamspeak, NULL) == 0;
	if (!worker_started || !teamspeak_thread_started) {
		stop();
		ts.logMessage("xtouch-daemon: can't start the threads of the plugin", LogLevel_ERROR, LOG_CHANNEL, 0);
		return 1;
	}
	return 0;
}

EXPORT void ts3plugin_shutdown(void) {
	stop();
}

EXPORT int ts3plugin_offersConfigure(void) {
	return PLUGIN_OFFERS_NO_CONFIGURE;
}

EXPORT int ts3plugin_requestAutoload(void) {
	return 0;
}

EXPORT void ts3plugin_freeMemory(void *data) {
	free(data);
}

// -- the callbacks: no calls into TeamSpeak -------------------------------------------------------------------------

EXPORT void ts3plugin_currentServerConnectionChanged(uint64 connection) {
	(void) connection;
	changed();
}

EXPORT void ts3plugin_onConnectStatusChangeEvent(uint64 connection, int status, unsigned int error) {
	(void) error;
	pthread_mutex_lock(&lock);
	if (status != STATUS_CONNECTION_ESTABLISHED && shown(connection)) {
		// gone at once: the next refresh may pick another tab
		participant_count = 0;
		channel[0] = '\0';
		shown_connection = 0;
		dirty = true;
	}
	stale = true;
	pthread_cond_signal(&wake);
	pthread_mutex_unlock(&lock);
}

// A client came, went or moved.
static void moved(uint64 connection, anyID client, uint64 from, uint64 to) {
	pthread_mutex_lock(&lock);
	if (shown(connection)) {
		if (client != own_client && from == shown_channel && to != shown_channel) {
			forget(client);
		} else if (to == shown_channel) {
			set_left(client, false);
		}
	}
	// also for another tab: it may be the one to show, and a refresh under way may not have seen it
	stale = true;
	pthread_cond_signal(&wake);
	pthread_mutex_unlock(&lock);
}

EXPORT void ts3plugin_onClientMoveEvent(uint64 connection, anyID client, uint64 from, uint64 to, int visibility,
										const char *message) {
	(void) visibility, (void) message;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientMoveSubscriptionEvent(uint64 connection, anyID client, uint64 from, uint64 to,
													int visibility) {
	(void) visibility;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientMoveTimeoutEvent(uint64 connection, anyID client, uint64 from, uint64 to,
											   int visibility, const char *message) {
	(void) visibility, (void) message;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientMoveMovedEvent(uint64 connection, anyID client, uint64 from, uint64 to, int visibility,
											 anyID mover, const char *mover_name, const char *mover_identity,
											 const char *message) {
	(void) visibility, (void) mover, (void) mover_name, (void) mover_identity, (void) message;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientKickFromChannelEvent(uint64 connection, anyID client, uint64 from, uint64 to,
												   int visibility, anyID kicker, const char *kicker_name,
												   const char *kicker_identity, const char *message) {
	(void) visibility, (void) kicker, (void) kicker_name, (void) kicker_identity, (void) message;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientKickFromServerEvent(uint64 connection, anyID client, uint64 from, uint64 to,
												  int visibility, anyID kicker, const char *kicker_name,
												  const char *kicker_identity, const char *message) {
	(void) visibility, (void) kicker, (void) kicker_name, (void) kicker_identity, (void) message;
	moved(connection, client, from, to);
}

EXPORT void ts3plugin_onClientBanFromServerEvent(uint64 connection, anyID client, uint64 from, uint64 to,
												 int visibility, anyID kicker, const char *kicker_name,
												 const char *kicker_identity, uint64 time, const char *message) {
	(void) visibility, (void) kicker, (void) kicker_name, (void) kicker_identity, (void) time, (void) message;
	moved(connection, client, from, to);
}

// A name or another property of a client, or the name of a channel.
static void updated(uint64 connection) {
	(void) connection;
	changed();
}

EXPORT void ts3plugin_onUpdateClientEvent(uint64 connection, anyID client, anyID invoker, const char *invoker_name,
										  const char *invoker_identity) {
	(void) client, (void) invoker, (void) invoker_name, (void) invoker_identity;
	updated(connection);
}

EXPORT void ts3plugin_onUpdateChannelEvent(uint64 connection, uint64 channel_id) {
	(void) channel_id;
	updated(connection);
}

EXPORT void ts3plugin_onUpdateChannelEditedEvent(uint64 connection, uint64 channel_id, anyID invoker,
												 const char *invoker_name, const char *invoker_identity) {
	(void) channel_id, (void) invoker, (void) invoker_name, (void) invoker_identity;
	updated(connection);
}

EXPORT void ts3plugin_onTalkStatusChangeEvent(uint64 connection, int status, int whisper, anyID client) {
	(void) whisper;
	bool talking = status == STATUS_TALKING;
	pthread_mutex_lock(&lock);
	struct participant *speaker = shown(connection) ? find(client) : NULL;
	if (speaker != NULL && speaker->talking != talking) {
		speaker->talking = talking;
		dirty = true;
	}
	pthread_mutex_unlock(&lock);
}

// The voice of a client before TeamSpeak's volume modifier and 3D positioning, 16 bit; every 10 ms while they talk.
EXPORT void ts3plugin_onEditPlaybackVoiceDataEvent(uint64 connection, anyID client, short *samples, int sample_count,
												   int channels) {
	pthread_mutex_lock(&lock);
	struct participant *speaker = shown(connection) ? find(client) : NULL;
	if (speaker == NULL || samples == NULL || sample_count <= 0 || channels <= 0) {
		pthread_mutex_unlock(&lock);
		return;
	}
	size_t count = (size_t) sample_count * (size_t) channels;
	int loudest = 0;
	for (size_t i = 0; i < count; i++) {
		int level = samples[i] < 0 ? -(int) samples[i] : samples[i];
		loudest = level > loudest ? level : loudest;
	}
	float pre_fader_peak = (float) loudest / 32768.0f;
	// the gain of the volume modifier: 20 * log10(volume / 100) dB
	float gain = (float) speaker->volume / 100.0f;
	float peak = pre_fader_peak * gain;
	if (peak > 1.0f) {
		peak = 1.0f;
	}
	if (peak > speaker->peak) {
		speaker->peak = peak;
	}
	if (pre_fader_peak > speaker->pre_fader_peak) {
		speaker->pre_fader_peak = pre_fader_peak;
	}
	bool silence = speaker->volume <= 0;
	pthread_mutex_unlock(&lock);
	if (silence) {
		// MIN_DB is quiet, not silent
		memset(samples, 0, count * sizeof(short));
	}
}
