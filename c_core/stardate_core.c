#include "stardate_core.h"

#include <math.h>
#include <stdio.h>
#include <string.h>

static int laia_is_null_or_empty(const char* value) {
    return value == NULL || value[0] == '\0';
}

int laia_is_leap_year(int year) {
    if (year % 400 == 0) {
        return 1;
    }
    if (year % 100 == 0) {
        return 0;
    }
    return (year % 4 == 0) ? 1 : 0;
}

int laia_days_in_month(int year, int month) {
    if (month < 1 || month > 12) {
        return 0;
    }

    static const int month_days[] = {
        31, 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31
    };

    if (month == 2 && laia_is_leap_year(year)) {
        return 29;
    }
    return month_days[month - 1];
}

int laia_day_of_year(int year, int month, int day) {
    if (month < 1 || month > 12 || day < 1) {
        return 0;
    }

    int total = 0;
    for (int m = 1; m < month; ++m) {
        int dim = laia_days_in_month(year, m);
        if (dim == 0) {
            return 0;
        }
        total += dim;
    }

    if (day > laia_days_in_month(year, month)) {
        return 0;
    }

    return total + day;
}

static int laia_validate_date_time(int year, int month, int day,
                                   int hour, int minute, int second) {
    if (month < 1 || month > 12) {
        return 0;
    }
    if (day < 1 || day > laia_days_in_month(year, month)) {
        return 0;
    }
    if (hour < 0 || hour > 23) {
        return 0;
    }
    if (minute < 0 || minute > 59) {
        return 0;
    }
    if (second < 0 || second > 59) {
        return 0;
    }
    return 1;
}

static double laia_seconds_in_day_of_year(int year, int month, int day,
                                          int hour, int minute, int second) {
    int doy = laia_day_of_year(year, month, day);
    if (doy <= 0) {
        return NAN;
    }
    return ((double)(doy - 1) * 86400.0) +
           ((double)hour * 3600.0) +
           ((double)minute * 60.0) +
           (double)second;
}

static int laia_days_in_year(int year) {
    return laia_is_leap_year(year) ? 366 : 365;
}

double laia_calculate_stardate(
    int year,
    int month,
    int day,
    int hour,
    int minute,
    int second,
    int offset_years
) {
    if (!laia_validate_date_time(year, month, day, hour, minute, second)) {
        return NAN;
    }

    int adjusted_year = year + offset_years;
    if (!laia_validate_date_time(adjusted_year, month, day, hour, minute, second)) {
        return NAN;
    }

    double elapsed = laia_seconds_in_day_of_year(
        adjusted_year, month, day, hour, minute, second);
    if (isnan(elapsed)) {
        return NAN;
    }

    double total = (double)laia_days_in_year(adjusted_year) * 86400.0;
    if (total <= 0.0) {
        return NAN;
    }

    double fraction_of_year = elapsed / total;
    return (((double)adjusted_year - 2323.0) * 1000.0) + (fraction_of_year * 1000.0);
}

int laia_format_personal_reference(
    char* buffer,
    size_t buffer_size,
    double stardate,
    int precision,
    const char* color,
    const char* tag
) {
    if (buffer == NULL || buffer_size == 0 || precision < 0) {
        return -1;
    }

    int has_color = !laia_is_null_or_empty(color);
    int has_tag = !laia_is_null_or_empty(tag);

    int written;
    if (has_color && has_tag) {
        written = snprintf(
            buffer,
            buffer_size,
            "(stardate: %.*f) [%s / %s]",
            precision,
            stardate,
            color,
            tag
        );
    } else if (has_color) {
        written = snprintf(
            buffer,
            buffer_size,
            "(stardate: %.*f) [%s]",
            precision,
            stardate,
            color
        );
    } else if (has_tag) {
        written = snprintf(
            buffer,
            buffer_size,
            "(stardate: %.*f) [%s]",
            precision,
            stardate,
            tag
        );
    } else {
        written = snprintf(buffer, buffer_size, "(stardate: %.*f)", precision, stardate);
    }

    if (written < 0 || (size_t)written >= buffer_size) {
        return -1;
    }

    return written;
}
