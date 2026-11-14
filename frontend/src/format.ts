// Display text for dates, times, counts and attribute codes. Money is never formatted here:
// it is a backend string and the UI shows it as sent.
const LOCALE = 'en-GB'
const HELSINKI = 'Europe/Helsinki'
const UTC = 'UTC'
const DATE_ONLY = /^\d{4}-\d{2}-\d{2}$/
const HAS_OFFSET = /(?:Z|[+-]\d{2}:?\d{2})$/

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

/** 1000 gives "1,000". */
export function formatCount(count: number): string {
  return count.toLocaleString(LOCALE)
}

/** FREE_FROM_LACTOSE gives "Free from lactose". The backend has no labels yet (open question 7). */
export function formatAttribute(code: string): string {
  const words = code.toLowerCase().replaceAll('_', ' ')
  return `${words.charAt(0).toUpperCase()}${words.slice(1)}`
}
