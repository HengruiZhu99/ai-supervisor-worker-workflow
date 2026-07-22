#include "vector_norm.hpp"

#include <cmath>
#include <iostream>
#include <vector>

int main() {
  const double measured = athenak_like::l2_norm(std::vector<double>{3.0, 4.0});
  if (std::abs(measured - 5.0) > 1.0e-12) {
    std::cerr << "expected L2 norm 5, got " << measured << '\n';
    return 1;
  }
  return 0;
}
