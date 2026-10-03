/*
 * Copyright (c) 2024 Anova Demo Systems
 * Proprietary — All rights reserved.
 * Company: Anova Demo
 *
 * Sample flight software unit for checklist demo (no-Docker Try Live).
 * Applicable coding standard: DO-178C (Software Considerations in Airborne Systems).
 */

#include <stdint.h>

/* Naming conventions: snake_case for locals, PREFIX_ for exported symbols. */

int32_t DEMO_airspeed_kts = 0;

/* error handling: clamp invalid input */
int32_t DEMO_set_airspeed(int32_t value)
{
    if (value < 0) {
        return -1; /* interface rejects negative */
    }
    DEMO_airspeed_kts = value;
    return 0;
}

/* Trace keywords for checklist: naming, comment, error handling, interface */
void DEMO_interface_tick(void)
{
    /* comment: periodic interface maintenance */
}
