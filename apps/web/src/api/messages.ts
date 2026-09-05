import { WorkspaceApiError } from './client';

export function requestErrorMessage(error: unknown): string {
  if (!(error instanceof WorkspaceApiError)) {
    return 'Не удалось выполнить запрос. Сведения не загружены.';
  }
  const reason = error.details?.reason;
  if (reason === 'request_in_flight') {
    return 'Проверка уже создаётся. Подождите немного и повторите с тем же запросом.';
  }
  if (reason === 'request_id_reused') {
    return 'Этот идентификатор уже использован для другого запроса. Изменение не применено.';
  }
  if (error.code === 'limit_exceeded') {
    return 'В проверке можно хранить до 20 компаний. Ни одна компания из этого списка не добавлена.';
  }
  if (error.status === 401) return 'Сессия не открыта. Войдите снова, чтобы загрузить проверки.';
  return error.message;
}
