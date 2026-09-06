import { describe, expect, it } from 'vitest';
import { formatDate, formatDateTime } from './formatDate';

describe('Отображение дат и времени', () => {
  it('учитывает смещение момента времени', () => {
    expect(formatDate('2026-09-05T21:00:00Z', 'Europe/Moscow')).toBe('6 сентября 2026 г.');
    expect(formatDateTime('2026-09-06T14:20:00+03:00', 'Europe/Moscow')).toBe('06.09.2026, 14:20');
    expect(formatDateTime('2026-09-06T14:20:00+03:00', 'UTC')).toBe('06.09.2026, 11:20');
  });
  it('не сдвигает календарную дату и не придумывает для неё время', () => {
    expect(formatDate('2026-09-06', 'America/Los_Angeles')).toBe('6 сентября 2026 г.');
    expect(formatDateTime('2026-09-06')).toBe('6 сентября 2026 г.');
  });
  it.each([null, undefined, '', '2026-02-30', '2026-02-30T12:00:00Z', 'не дата'])('обрабатывает некорректное значение %s', (value) => {
    expect(formatDate(value)).toBe('Дата не указана');
    expect(formatDateTime(value)).toBe('Дата не указана');
  });
});
