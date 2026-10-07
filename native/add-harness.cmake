# An external CMake project hook; upstream source files are never patched.
if(PROJECT_NAME STREQUAL "xournalpp" AND NOT TARGET inkstages-fixture)
  add_executable(inkstages-fixture EXCLUDE_FROM_ALL "${INKSTAGES_HARNESS_SOURCE}")
  target_compile_features(inkstages-fixture PRIVATE cxx_std_20)
  target_link_libraries(inkstages-fixture PRIVATE xoj::core xoj::util)
endif()
