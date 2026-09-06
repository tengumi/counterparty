import { Button } from "@alfalab/core-components-button";
import type { ComponentProps } from "react";

export function Action(props: ComponentProps<typeof Button>) {
  return <Button size={40} view="secondary" {...props} />;
}

export function Icon({
  name,
}: {
  name:
    | "search"
    | "grid"
    | "folder"
    | "file"
    | "spark"
    | "arrow"
    | "plus"
    | "chat"
    | "expand"
    | "minimize"
    | "close";
}) {
  const paths = {
    search: "m21 21-5-5M19 11a8 8 0 1 1-16 0 8 8 0 0 1 16 0",
    grid: "M3 3h7v7H3zM14 3h7v7h-7zM3 14h7v7H3zM14 14h7v7h-7z",
    folder: "M3 7V4h6l2 3h10v13H3z",
    file: "M5 3h9l5 5v13H5zM14 3v6h5M8 13h8M8 17h6",
    spark: "m12 3 2.5 6.5L21 12l-6.5 2.5L12 21l-2.5-6.5L3 12l6.5-2.5z",
    arrow: "M5 12h14m-6-6 6 6-6 6",
    plus: "M12 5v14M5 12h14",
    chat: "M21 11a8 8 0 0 1-8 8H5l-3 3V11a8 8 0 0 1 8-8h3a8 8 0 0 1 8 8ZM7 9h9M7 13h6",
    expand: "M14 4h6v6M20 4l-7 7M10 20H4v-6M4 20l7-7",
    minimize: "M20 4l-7 7m0-6v6h6M4 20l7-7m-6 0h6v6",
    close: "m6 6 12 12M6 18 18 6",
  };
  return (
    <svg
      width="20"
      height="20"
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="1.7"
      strokeLinecap="round"
      strokeLinejoin="round"
      aria-hidden="true"
    >
      <path d={paths[name]} />
    </svg>
  );
}

const banks: Record<string, string> = {
  GREEN: "Надёжный",
  YELLOW: "Требует внимания",
  RED: "В зоне риска",
  GREY: "Нет оценки",
};
export function bankLabel(level: string | null | undefined): string {
  if (level == null) return "Сигнал не передан";
  return Object.hasOwn(banks, level) ? banks[level] : "Сигнал не распознан";
}
export function Bank({ level }: { level?: string | null }) {
  return (
    <span className={`bank-badge ${(level || "GREY").toLowerCase()}`}>
      <i />
      {bankLabel(level)}
    </span>
  );
}
export const date = (value: string) =>
  new Date(value).toLocaleDateString("ru-RU", { timeZone: "Europe/Moscow" });
