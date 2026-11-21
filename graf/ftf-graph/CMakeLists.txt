cmake_minimum_required(VERSION 3.20)
project(ftf_graph CXX)

set(CMAKE_CXX_STANDARD 20)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

add_executable(ftf-graph src/main.cpp)
target_include_directories(ftf-graph PRIVATE third_party)
target_compile_options(ftf-graph PRIVATE -Wall -Wextra -O2)
