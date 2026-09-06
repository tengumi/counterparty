import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { afterEach, describe, expect, it, vi } from "vitest";
import { ChatPanel, startWaitingTimer, waitingLabel } from "./ChatPanel";

vi.mock("@alfalab/core-components-button", () => ({
  Button: ({ children, ...props }: { children: import("react").ReactNode }) =>
    createElement("button", props, children),
}));

describe("Ожидание ответа", () => {
  afterEach(() => vi.useRealTimers());

  it("меняет подписи без выдуманных этапов и обещаний скорого завершения", () => {
    expect(waitingLabel(0)).toBe("Обрабатываю запрос…");
    expect(waitingLabel(7999)).toBe(waitingLabel(0));
    expect(waitingLabel(8000)).toBe("Готовлю ответ…");
    expect(waitingLabel(20000)).toBe("Ответ ещё готовится…");
    expect(waitingLabel(45000)).toBe("Запрос всё ещё обрабатывается…");
    expect(waitingLabel(180000)).toBe(waitingLabel(45000));
  });

  it("останавливает таймер после ответа и начинает новый запрос с нуля", () => {
    vi.useFakeTimers();
    const update = vi.fn();
    const stop = startWaitingTimer(update);
    expect(update).toHaveBeenLastCalledWith(0);
    vi.advanceTimersByTime(8000);
    expect(waitingLabel(update.mock.lastCall![0])).toBe("Готовлю ответ…");
    stop();
    expect(vi.getTimerCount()).toBe(0);
    const calls = update.mock.calls.length;
    vi.advanceTimersByTime(60000);
    expect(update).toHaveBeenCalledTimes(calls);
    const stopNext = startWaitingTimer(update);
    expect(update).toHaveBeenLastCalledWith(0);
    stopNext();
  });
});

describe("Компактный ввод в расширенном чате", () => {
  const render = (expanded: boolean, busy = false) =>
    renderToStaticMarkup(
      createElement(ChatPanel, {
        messages: [{ role: "user", text: "Мой вопрос" }],
        busy,
        send: vi.fn(),
        group: false,
        source: vi.fn(),
        expanded,
        toggleExpanded: vi.fn(),
      }),
    );

  it("при расширении оставляет больше места сообщениям, убирает подсказку клавиатуры", () => {
    expect(render(false)).toMatch(/<textarea[^>]*rows="2"/);
    const expanded = render(true);
    expect(expanded).toContain('data-expanded="true"');
    expect(expanded).toMatch(/<textarea[^>]*rows="1"/);
    expect(expanded).toContain("Мой вопрос");
    expect(expanded).toContain('aria-label="Вернуть чат сбоку"');
    expect(expanded).not.toContain("chat-keyboard-hint");
    expect(expanded).not.toContain("Shift+Enter");
  });

  it("ожидание исчезает после завершения, отправка остаётся заблокирована во время запроса", () => {
    expect(render(false, true)).toContain("Обрабатываю запрос…");
    expect(render(false, false)).not.toContain("Обрабатываю запрос…");
    expect(render(false, true)).toMatch(/<textarea[^>]*disabled/);
  });
});
