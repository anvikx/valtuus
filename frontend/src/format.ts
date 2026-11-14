// Display text for dates, times, counts and attribute codes. Money is never formatted here:
// it is a backend string and the UI shows it as sent.
const LOCALE = 'en-GB'
const HELSINKI = 'Europe/Helsinki'
const UTC = 'UTC'
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/
const SECONDS_PER_MINUTE = 60
const SECONDS_PER_HOUR = 3600

interface Instant {
  readonly date: Date
  readonly timeZone: string
}

// The backend sends three kinds of time value:
//   2026-11-16                  a date only (delivery date)
//   2026-11-15T17:00:00         no offset: the gateway's wall clock (cut off, approve_before)
//   2026-11-14T10:04:12+02:00   with offset: a moment, shown in Helsinki time
// The first two are read as UTC and shown in UTC, so their clock digits stay as sent.
function toInstant(value: string): Instant {
  if (DATE_ONLY.test(value)) {
    return {
      date: new Date(`${value}T00:00:00Z`),
      timeZone: UTC,
    }
  }

  if (HAS_OFFSET.test(value)) {
    return {
      date: new Date(value),
      timeZone: HELSINKI,
    }
  }

  return {
    date: new Date(`${value}Z`),
    timeZone: UTC,
  }
}

function partsOf(value: string, options: Intl.DateTimeFormatOptions): Record<string, string> {
  const { date, timeZone } = toInstant(value)
  const formatter = new Intl.DateTimeFormat(LOCALE, {
    ...options,
    timeZone,
    hourCycle: 'h23',
  })

  return Object.fromEntries(formatter.formatToParts(date).map((part) => [part.type, part.value]))
}

/** "Mon 16 Nov" */
export function formatDate(value: string): string {
  const { weekday, day, month } = partsOf(value, {
    weekday: 'short',
    day: 'numeric',
    month: 'short',
  })
  return `${weekday} ${day} ${month}`
}

/** "Sun 15 Nov 17:00" */
export function formatDateTime(value: string): string {
  const { hour, minute } = partsOf(value, {
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${formatDate(value)} ${hour}:${minute}`
}

/** "10:00:05" */
export function formatClock(value: string): string {
  const { hour, minute, second } = partsOf(value, {
    hour: '2-digit',
    minute: '2-digit',
    second: '2-digit',
  })
  return `${hour}:${minute}:${second}`
}

/** "10:00" */
export function formatHourMinute(value: string): string {
  const { hour, minute } = partsOf(value, {
    hour: '2-digit',
    minute: '2-digit',
  })
  return `${hour}:${minute}`
}

/** "41 s", "4 min 7 s" or "31 h 0 min". */
export function formatElapsed(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / SECONDS_PER_HOUR)
  const minutes = Math.floor((totalSeconds % SECONDS_PER_HOUR) / SECONDS_PER_MINUTE)
  const seconds = totalSeconds % SECONDS_PER_MINUTE
  if (hours > 0) {
    return `${hours} h ${minutes} min`
  }

  return minutes > 0 ? `${minutes} min ${seconds} s` : `${seconds} s`
}

/** "28 h left", "40 min left" or "Time is up", from now to a deadline. */
export function formatTimeLeft(deadline: string, now: Date): string {
  const seconds = (toInstant(deadline).date.getTime() - now.getTime()) / 1000
  if (seconds <= 0) {
    return 'Time is up'
  }

  // Rounds down, so the page never promises more time than is left. The last minute shows as 1.
  const hours = Math.floor(seconds / SECONDS_PER_HOUR)
  if (hours > 0) {
    return `${hours} h left`
  }

  return `${Math.max(1, Math.floor(seconds / SECONDS_PER_MINUTE))} min left`
}

/** 1000 gives "1,000". */
export function formatCount(count: number): string {
  return count.toLocaleString(LOCALE)
}

/** FREE_FROM_LACTOSE gives "Free from lactose". The backend has no labels yet. */
export function formatAttribute(code: string): string {
  const words = code.toLowerCase().replaceAll('_', ' ')
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`
}

// The choices the search asks the buyer about. A rule set here stops the question.
export const REQUIRED_ATTRIBUTE_CODES: readonly string[] = [
  'FREE_FROM_LACTOSE',
  'LOW_LACTOSE',
  'FREE_FROM_GLUTEN',
  'FREE_FROM_WHEAT',
  'FREE_FROM_EGGS',
  'FREE_FROM_SOY',
  'VEGAN',
  'FREE_FROM_FAT',
  'LOW_FAT',
  'EU_ORGANIC_FARMING',
]

// GS1 allergen type codes of the 14 EU allergens, as the catalog declares them. The backend
// matches forbidden_allergens against these codes, so the mandate must store the code.
export const ALLERGEN_WORDS: Readonly<Record<string, string>> = {
  AM: 'Milk',
  AW: 'Cereals with gluten',
  AE: 'Eggs',
  AF: 'Fish',
  AC: 'Crustaceans',
  UM: 'Molluscs',
  AP: 'Peanuts',
  AN: 'Tree nuts',
  AY: 'Soy',
  AS: 'Sesame',
  BC: 'Celery',
  BM: 'Mustard',
  NL: 'Lupin',
  AU: 'Sulphites',
}

/** AM gives "Milk". A code outside the 14 shows as it is, so a stored value is never hidden. */
export function formatAllergen(code: string): string {
  return ALLERGEN_WORDS[code] ?? code
}
