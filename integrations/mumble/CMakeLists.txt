# The Mumble plugin of xtouch-daemon (see docs/integrations/mumble.md).
#
#   cmake -S integrations/mumble -B integrations/mumble/build
#   cmake --build integrations/mumble/build
#
# builds libxtouch-daemon.so and the bundle xtouch-daemon.mumble_plugin (a zip of the library and manifest.xml),
# which Mumble installs: `mumble -m integrations/mumble/build/xtouch-daemon.mumble_plugin`
# (or `xtouch-daemon mumble-plugin --install`). -DXTD_TESTS=ON also builds
# fake_mumble, the host the tests load the plugin into (tests/voip/test_mumble_plugin.py).
cmake_minimum_required(VERSION 3.15)

# the version of xtouch-daemon (pyproject.toml), which Mumble shows for the plugin
set(XTD_PYPROJECT "${CMAKE_CURRENT_SOURCE_DIR}/../../pyproject.toml")
if(EXISTS "${XTD_PYPROJECT}")
	file(STRINGS "${XTD_PYPROJECT}" XTD_VERSION_LINE REGEX "^version = ")
	string(REGEX MATCH "[0-9]+\\.[0-9]+\\.[0-9]+" XTD_VERSION "${XTD_VERSION_LINE}")
endif()
if(NOT XTD_VERSION)
	# the sources on their own, outside the repository
	set(XTD_VERSION 0.0.0)
endif()

project(xtouch_daemon_mumble_plugin
	VERSION ${XTD_VERSION}
	DESCRIPTION "The Mumble plugin of xtouch-daemon"
	LANGUAGES C
)

option(XTD_TESTS "Build the fake Mumble the tests load the plugin into" OFF)

set(CMAKE_C_STANDARD 11)
set(CMAKE_C_STANDARD_REQUIRED ON)
set(CMAKE_C_VISIBILITY_PRESET hidden)
if(NOT CMAKE_BUILD_TYPE)
	set(CMAKE_BUILD_TYPE Release)
endif()

find_package(Threads REQUIRED)

add_library(xtouch-daemon SHARED plugin.c)
target_include_directories(xtouch-daemon PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
target_compile_options(xtouch-daemon PRIVATE -Wall -Wextra -Wno-unused-parameter)
target_compile_definitions(xtouch-daemon PRIVATE
	XTD_PLUGIN_VERSION_MAJOR=${PROJECT_VERSION_MAJOR}
	XTD_PLUGIN_VERSION_MINOR=${PROJECT_VERSION_MINOR}
	XTD_PLUGIN_VERSION_PATCH=${PROJECT_VERSION_PATCH}
)
target_link_libraries(xtouch-daemon PRIVATE Threads::Threads m)

# the bundle: manifest.xml and the library, nothing else (Mumble's docs/dev/plugins/Bundling.md)
if(CMAKE_SIZEOF_VOID_P EQUAL 8)
	set(XTD_ARCH x64)
else()
	set(XTD_ARCH x86)
endif()
set(XTD_BUNDLE_DIR "${CMAKE_CURRENT_BINARY_DIR}/bundle")
configure_file(manifest.xml.in "${XTD_BUNDLE_DIR}/manifest.xml" @ONLY)
add_custom_command(
	OUTPUT "${CMAKE_CURRENT_BINARY_DIR}/xtouch-daemon.mumble_plugin"
	COMMAND ${CMAKE_COMMAND} -E copy "$<TARGET_FILE:xtouch-daemon>" "${XTD_BUNDLE_DIR}/libxtouch-daemon.so"
	COMMAND ${CMAKE_COMMAND} -E tar cf "${CMAKE_CURRENT_BINARY_DIR}/xtouch-daemon.mumble_plugin" --format=zip
		manifest.xml libxtouch-daemon.so
	WORKING_DIRECTORY "${XTD_BUNDLE_DIR}"
	DEPENDS xtouch-daemon "${XTD_BUNDLE_DIR}/manifest.xml"
	COMMENT "Bundling xtouch-daemon.mumble_plugin"
)
add_custom_target(bundle ALL DEPENDS "${CMAKE_CURRENT_BINARY_DIR}/xtouch-daemon.mumble_plugin")

if(XTD_TESTS)
	add_executable(fake_mumble test/fake_mumble.c)
	target_include_directories(fake_mumble PRIVATE "${CMAKE_CURRENT_SOURCE_DIR}/include")
	target_compile_options(fake_mumble PRIVATE -Wall -Wextra -Wno-unused-parameter)
	target_link_libraries(fake_mumble PRIVATE ${CMAKE_DL_LIBS})
endif()
