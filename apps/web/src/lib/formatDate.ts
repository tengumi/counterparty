const calendarDate = /^\d{4}-\d{2}-\d{2}$/;
const isoDate = /^\d{4}-\d{2}-\d{2}(?:T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?(?:Z|[+-]\d{2}:\d{2}))?$/;
const unavailable = 'Дата не указана';

function parseDate(value: string | null | undefined): Date | null {
  if (!value || !isoDate.test(value)) return null;
  const day = new Date(`${value.slice(0, 10)}T00:00:00Z`);
  if (Number.isNaN(day.valueOf()) || day.toISOString().slice(0, 10) !== value.slice(0, 10)) return null;
  const date = new Date(value);
  return Number.isNaN(date.valueOf()) ? null : date;
}

/** Моменты времени показываем в часовом поясе пользователя; календарные даты не сдвигаем. */
export function formatDate(value: string | null | undefined, timeZone?: string): string {
  const date = parseDate(value);
  if (!date) return unavailable;
  return new Intl.DateTimeFormat('ru-RU', {
    day: 'numeric', month: 'long', year: 'numeric',
    timeZone: calendarDate.test(value!) ? 'UTC' : timeZone,
  }).format(date);
}

export function formatDateTime(value: string | null | undefined, timeZone?: string): string {
  const date = parseDate(value);
  if (!date) return unavailable;
  if (calendarDate.test(value!)) return formatDate(value);
  return new Intl.DateTimeFormat('ru-RU', {
    day: '2-digit', month: '2-digit', year: 'numeric',
    hour: '2-digit', minute: '2-digit', hour12: false, timeZone,
  }).format(date);
}
