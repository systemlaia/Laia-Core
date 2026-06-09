#include <math.h>
#include <stdio.h>
#include <string.h>

#include "stardate_core.h"

static int approx_equal(double a, double b, double tolerance) {
    return fabs(a - b) <= tolerance;
}

static int expect_double(const char* name, double actual, double expected,
                         double tolerance) {
    if (!approx_equal(actual, expected, tolerance)) {
        printf("FAIL %s: actual=%.6f expected=%.6f\n", name, actual, expected);
        return 1;
    }
    return 0;
}

static int expect_nan(const char* name, double value) {
    if (!isnan(value)) {
        printf("FAIL %s: expected NAN but got %.6f\n", name, value);
        return 1;
    }
    return 0;
}

static int expect_string(const char* name, const char* actual,
                         const char* expected) {
    if (strcmp(actual, expected) != 0) {
        printf("FAIL %s: actual='%s' expected='%s'\n", name, actual, expected);
        return 1;
    }
    return 0;
}

int main(void) {
    int failures = 0;
    const double tolerance = 0.1;

    failures += expect_double(
        "vector-start-of-year",
        laia_calculate_stardate(2026, 1, 1, 0, 0, 0, 347),
        50000.0,
        tolerance
    );

    failures += expect_double(
        "vector-midyear-2026",
        laia_calculate_stardate(2026, 6, 7, 21, 14, 0, 347),
        50432.6,
        tolerance
    );

    failures += expect_double(
        "vector-end-of-year",
        laia_calculate_stardate(2026, 12, 31, 23, 59, 0, 347),
        51000.0,
        tolerance
    );

    failures += expect_double(
        "vector-no-offset",
        laia_calculate_stardate(2026, 6, 7, 21, 14, 0, 0),
        -296567.4,
        tolerance
    );

    failures += expect_nan(
        "invalid-month",
        laia_calculate_stardate(2026, 13, 1, 0, 0, 0, 347)
    );

    failures += expect_nan(
        "invalid-day",
        laia_calculate_stardate(2026, 2, 30, 0, 0, 0, 347)
    );

    failures += expect_nan(
        "invalid-hour",
        laia_calculate_stardate(2026, 6, 7, 24, 0, 0, 347)
    );

    failures += expect_nan(
        "invalid-minute",
        laia_calculate_stardate(2026, 6, 7, 21, 60, 0, 347)
    );

    failures += expect_nan(
        "invalid-second",
        laia_calculate_stardate(2026, 6, 7, 21, 14, 60, 347)
    );

    char buffer[128];
    int written;

    written = laia_format_personal_reference(buffer, sizeof(buffer), 50123.4, 1, NULL, NULL);
    if (written < 0) {
        printf("FAIL formatter-basic: error returned\n");
        failures += 1;
    } else {
        failures += expect_string("formatter-basic", buffer, "(stardate: 50123.4)");
    }

    written = laia_format_personal_reference(buffer, sizeof(buffer), 50123.4, 1, "Yellow", NULL);
    if (written < 0) {
        printf("FAIL formatter-color-only: error returned\n");
        failures += 1;
    } else {
        failures += expect_string("formatter-color-only", buffer, "(stardate: 50123.4) [Yellow]");
    }

    written = laia_format_personal_reference(buffer, sizeof(buffer), 50123.4, 1, NULL, "Idea");
    if (written < 0) {
        printf("FAIL formatter-tag-only: error returned\n");
        failures += 1;
    } else {
        failures += expect_string("formatter-tag-only", buffer, "(stardate: 50123.4) [Idea]");
    }

    written = laia_format_personal_reference(buffer, sizeof(buffer), 50123.4, 1, "Yellow", "Idea");
    if (written < 0) {
        printf("FAIL formatter-color-tag: error returned\n");
        failures += 1;
    } else {
        failures += expect_string("formatter-color-tag", buffer, "(stardate: 50123.4) [Yellow / Idea]");
    }

    if (failures == 0) {
        printf("All C tests passed.\n");
    } else {
        printf("C tests failed: %d\n", failures);
    }

    return failures == 0 ? 0 : 1;
}
