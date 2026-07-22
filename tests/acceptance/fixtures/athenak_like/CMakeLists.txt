cmake_minimum_required(VERSION 3.20)
project(aiflow_athenak_like LANGUAGES CXX)

enable_testing()
add_executable(test_vector_norm tests/test_vector_norm.cpp)
target_compile_features(test_vector_norm PRIVATE cxx_std_17)
target_include_directories(test_vector_norm PRIVATE include)
add_test(NAME vector_norm COMMAND test_vector_norm)
