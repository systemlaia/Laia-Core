#ifndef LAIA_STARDATE_CORE_H
#define LAIA_STARDATE_CORE_H

#include <stddef.h>

#ifdef __cplusplus
extern "C" {
#endif

int laia_is_leap_year(int year);
int laia_days_in_month(int year, int month);
int laia_day_of_year(int year, int month, int day);

double laia_calculate_stardate(
    int year,
    int month,
    int day,
    int hour,
    int minute,
    int second,
    int offset_years
);

int laia_format_personal_reference(
    char* buffer,
    size_t buffer_size,
    double stardate,
    int precision,
    const char* color,
    const char* tag
);

#ifdef __cplusplus
}
#endif

#endif /* LAIA_STARDATE_CORE_H */
