# The TeamSpeak 3 plugin of xtouch-daemon (see docs/guides/teamspeak.md and docs/development/teamspeak-plugin.md).
#
#   cmake -S integrations/teamspeak -B integrations/teamspeak/build
#   cmake --build integrations/teamspeak/build
#
# builds xtouch-daemon_linux_amd64.so, which TeamSpeak loads from ~/.ts3client/plugins
# (`xtouch-daemon teamspeak-plugin --install` copies it there). -DXTD_TESTS=ON also builds fake_teamspeak, the host
# the tests load the plugin into (tests/voip/test_teamspeak_plugin.py).
#
# The headers of TeamSpeak's plugin SDK (https://github.com/TeamSpeak-Systems/ts3client-pluginsdk) are TeamSpeak's,
# "all rights reserved", so they are not in this repository: the first build downloads them, at the commit below and
# checked against its hash, into sdk/ (ignored by git), and later builds use them from there, also offline.
# -DTS3_SDK_DIR=<directory> uses another copy (the directory with include/ts3_functions.h).
cmake_minimum_required(VERSION 3.21)

# the version of xtouch-daemon (pyproject.toml), which TeamSpeak shows for the plugin
set(XTD_PYPROJECT "${CMAKE_CURRENT_SOURCE_DIR}/../../pyproject.toml")
if(EXISTS "${XTD_PYPROJECT}")
	file(STRINGS "${XTD_PYPROJECT}" XTD_VERSION_LINE REGEX "^version = ")
	string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+" XTD_VERSION "${XTD_VERSION_LINE}")
endif()
if(NOT XTD_VERSION)
	# the sources on their own, outside the repository
	set(XTD_VERSION 0.0.0)
endif()

project(xtouch_daemon_teamspeak_plugin
	VERSION ${XTD_VERSION}
	DESCRIPTION "The TeamSpeak 3 plugin of xtouch-daemon"
	LANGUAGES C
)

option(XTD_TESTS "Build the fake TeamSpeak the tests load the plugin into" OFF)

# plugin API 26: TeamSpeak 3.6.0 and later
set(XTD_TS3_SDK_COMMIT 4aa90a53aa150cbf81e13bc97e68c0431b26499f)
set(XTD_TS3_SDK_SHA256 d5fa5655a85cbd4367728df95fad92372a1c9804f5a5357d3b60af07382aec4c)
set(TS3_SDK_DIR "${CMAKE_CURRENT_SOURCE_DIR}/sdk/${XTD_TS3_SDK_COMMIT}" CACHE PATH
	"TeamSpeak's plugin SDK, the directory with include/ts3_functions.h (downloaded if it is not there)")

if(NOT EXISTS "${TS3_SDK_DIR}/include/ts3_functions.h")
	set(XTD_TS3_SDK_URL
		"https://github.com/TeamSpeak-Systems/ts3client-pluginsdk/archive/${XTD_TS3_SDK_COMMIT}.tar.gz")
	set(XTD_TS3_SDK_ARCHIVE "${CMAKE_CURRENT_BINARY_DIR}/ts3client-pluginsdk.tar.gz")
	message(STATUS "Downloading TeamSpeak's plugin SDK from ${XTD_TS3_SDK_URL}")
	file(DOWNLOAD "${XTD_TS3_SDK_URL}" "${XTD_TS3_SDK_ARCHIVE}"
		EXPECTED_HASH SHA256=${XTD_TS3_SDK_SHA256} STATUS XTD_TS3_SDK_STATUS TLS_VERIFY ON)
	list(GET XTD_TS3_SDK_STATUS 0 XTD_TS3_SDK_CODE)
	if(NOT XTD_TS3_SDK_CODE EQUAL 0)
		list(GET XTD_TS3_SDK_STATUS 1 XTD_TS3_SDK_ERROR)
		message(FATAL_ERROR "Can't download TeamSpeak's plugin SDK (${XTD_TS3_SDK_ERROR}): "
			"connect to the internet once, or give a copy with -DTS3_SDK_DIR=<directory>")
	endif()
	# into a directory of its own first: builds that run at the same time don't see half of it
	string(RANDOM LENGTH 8 XTD_TS3_SDK_RANDOM)
	get_filename_component(XTD_TS3_SDK_PARENT "${TS3_SDK_DIR}" DIRECTORY)
	set(XTD_TS3_SDK_UNPACKED "${XTD_TS3_SDK_PARENT}/.unpacking-${XTD_TS3_SDK_RANDOM}")
	file(ARCHIVE_EXTRACT INPUT "${XTD_TS3_SDK_ARCHIVE}" DESTINATION "${XTD_TS3_SDK_UNPACKED}")
	file(RENAME "${XTD_TS3_SDK_UNPACKED}/ts3client-pluginsdk-${XTD_TS3_SDK_COMMIT}" "${TS3_SDK_DIR}"
		RESULT XTD_TS3_SDK_RENAMED)
	file(REMOVE_RECURSE "${XTD_TS3_SDK_UNPACKED}" "${XTD_TS3_SDK_ARCHIVE}")
	if(NOT EXISTS "${TS3_SDK_DIR}/include/ts3_functions.h")
		message(FATAL_ERROR "TeamSpeak's plugin SDK is not in ${TS3_SDK_DIR}: ${XTD_TS3_SDK_RENAMED}")
	endif()
endif()

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
if(NOT CMAKE_BUILD_TYPE)
	set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Threads REQUIRED)

# TeamSpeak's name for the plugin of this platform, as in its .ts3_plugin packages
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
	set(XTD_PLATFORM linux_amd64)
else()
	set(XTD_PLATFORM linux_x86)
endif()

add_library(xtouch-daemon-teamspeak SHARED plugin.c)
set_target_properties(xtouch-daemon-teamspeak PROPERTIES PREFIX "" OUTPUT_NAME "xtouch-daemon_${XTD_PLATFORM}")
# the SDK's headers are someone else's: no warnings of theirs
target_include_directories(xtouch-daemon-teamspeak SYSTEM PRIVATE "${TS3_SDK_DIR}/include")
target_compile_options(xtouch-daemon-teamspeak PRIVATE -Wall -Wextra)
target_compile_definitions(xtouch-daemon-teamspeak PRIVATE XTD_PLUGIN_VERSION="${PROJECT_VERSION}")
target_link_libraries(xtouch-daemon-teamspeak PRIVATE Threads::Threads m)

if(XTD_TESTS)
	add_executable(fake_teamspeak test/fake_teamspeak.c)
	target_include_directories(fake_teamspeak SYSTEM PRIVATE "${TS3_SDK_DIR}/include")
	target_compile_options(fake_teamspeak PRIVATE -Wall -Wextra -Wno-unused-parameter)
	target_link_libraries(fake_teamspeak PRIVATE Threads::Threads m ${CMAKE_DL_LIBS})
endif()
