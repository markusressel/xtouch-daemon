// A Mumble for the tests of the plugin (tests/test_mumble_plugin.py): loads the plugin like Mumble does, gives it the
// Mumble API of a made-up server, and calls its callbacks as a script on stdin says, one command per line:
//
//   connect LOCAL CHANNEL      the local user LOCAL in CHANNEL, connected and synchronized
//   user ID CHANNEL NAME       a user comes, or moves to another channel
//   leave ID                   a user leaves the server
//   talk ID STATE              a talking state (0 passive, 1 talking, 2 whispering, 3 shouting, 4 talking muted)
//   audio ID VALUE             a voice packet of ID with every sample VALUE: prints "audio MODIFIED SAMPLE"
//   disconnect                 the connection ends
//   quit                       shuts the plugin down
//
// It answers every command with "ok" once the plugin returned.
#define MUMBLE_PLUGIN_API_MAJOR_MACRO 1
#define MUMBLE_PLUGIN_API_MINOR_MACRO 0
#define MUMBLE_PLUGIN_API_PATCH_MACRO 0
#define MUMBLE_PLUGIN_NO_DEFAULT_FUNCTION_DEFINITIONS
#include "MumblePlugin.h"

#include <dlfcn.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>

#define MAX_USERS 64

struct user {
	mumble_userid_t id;
	mumble_channelid_t channel;
	char name[128];
};

static struct user users[MAX_USERS];
static size_t user_count;
static bool connected;
static mumble_userid_t local_user;

static struct user *find(mumble_userid_t id) {
	for (size_t i = 0; i < user_count; i++) {
		if (users[i].id == id) {
			return &users[i];
		}
	}
	return NULL;
}

static mumble_error_t free_memory(mumble_plugin_id_t caller, const void *pointer) {
	free((void *) pointer);
	return MUMBLE_STATUS_OK;
}

static mumble_error_t active_connection(mumble_plugin_id_t caller, mumble_connection_t *connection) {
	if (!connected) {
		return MUMBLE_EC_NO_ACTIVE_CONNECTION;
	}
	*connection = 1;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t synchronized(mumble_plugin_id_t caller, mumble_connection_t connection, bool *result) {
	*result = connected;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t local_user_id(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t *id) {
	*id = local_user;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t user_name(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
								const char **name) {
	struct user *user = find(id);
	if (user == NULL) {
		return MUMBLE_EC_USER_NOT_FOUND;
	}
	*name = strdup(user->name);
	return MUMBLE_STATUS_OK;
}

static mumble_error_t channel_name(mumble_plugin_id_t caller, mumble_connection_t connection,
								   mumble_channelid_t channel, const char **name) {
	char *text = malloc(32);
	snprintf(text, 32, "Channel %d", channel);
	*name = text;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t channel_of_user(mumble_plugin_id_t caller, mumble_connection_t connection, mumble_userid_t id,
									  mumble_channelid_t *channel) {
	struct user *user = find(id);
	if (user == NULL) {
		return MUMBLE_EC_USER_NOT_FOUND;
	}
	*channel = user->channel;
	return MUMBLE_STATUS_OK;
}

static mumble_error_t users_in_channel(mumble_plugin_id_t caller, mumble_connection_t connection,
									   mumble_channelid_t channel, mumble_userid_t **list, size_t *count) {
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

static mumble_error_t log_message(mumble_plugin_id_t caller, const char *message) {
	printf("log %s\n", message);
	return MUMBLE_STATUS_OK;
}

static void *symbol(void *library, const char *name) {
	void *found = dlsym(library, name);
	if (found == NULL) {
		fprintf(stderr, "the plugin has no %s\n", name);
		exit(2);
	}
	return found;
}

int main(int argc, char **argv) {
	if (argc != 2) {
		fprintf(stderr, "usage: %s PLUGIN.so\n", argv[0]);
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
	api.log = log_message;
	register_api(&api);
	if (init(7) != MUMBLE_STATUS_OK) {
		fprintf(stderr, "init failed\n");
		return 1;
	}
	printf("ready\n");
	fflush(stdout);

	char line[256];
	while (fgets(line, sizeof(line), stdin) != NULL) {
		unsigned id;
		int channel, state;
		float value;
		char text[128];
		if (sscanf(line, "connect %u %d", &id, &channel) == 2) {
			local_user = id;
			if (find(id) == NULL && user_count < MAX_USERS) {
				users[user_count++] = (struct user) {id, channel, "me"};
			}
			connected = true;
			synchronized_event(1);
		} else if (sscanf(line, "user %u %d %127[^\n]", &id, &channel, text) == 3) {
			struct user *user = find(id);
			mumble_channelid_t previous = user ? user->channel : -1;
			if (user == NULL && user_count < MAX_USERS) {
				user = &users[user_count++];
			}
			*user = (struct user) {id, channel, ""};
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
			float pcm[4] = {value, value, value, value};
			bool modified = audio_event(pcm, 2, 2, 48000, true, id);
			printf("audio %d %.3f\n", modified, pcm[0]);
		} else if (strncmp(line, "disconnect", 10) == 0) {
			connected = false;
			disconnected_event(1);
		} else if (strncmp(line, "quit", 4) == 0) {
			shutdown();
			printf("ok\n");
			fflush(stdout);
			break;
		} else {
			printf("unknown %s", line);
		}
		printf("ok\n");
		fflush(stdout);
	}
	dlclose(plugin);
	return 0;
}
