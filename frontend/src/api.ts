export async function api<T>(
  path: string,
  options: RequestInit = {},
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(path, {
      ...options,
      headers: { "Content-Type": "application/json", ...options.headers },
    });
  } catch {
    throw new Error(
      "Нет связи с приложением. Проверьте, что локальный сервер запущен, и повторите запрос.",
    );
  }
  if (!response.ok) {
    const error = await response.json().catch(() => ({}));
    throw new Error(
      typeof error?.detail === "string" && error.detail.trim()
        ? error.detail
        : response.status === 422
          ? "Не удалось принять запрос. Проверьте введённые данные и повторите попытку."
          : "Не удалось выполнить запрос. Попробуйте ещё раз.",
    );
  }
  if (response.status === 204) return undefined as T;
  try {
    return await response.json();
  } catch {
    throw new Error("Получен неполный ответ приложения. Повторите запрос.");
  }
}

export const post = <T>(path: string, data: unknown) =>
  api<T>(path, { method: "POST", body: JSON.stringify(data) });
