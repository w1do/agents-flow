import { fireEvent, render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { App } from "@/app";

export async function login() {
  fireEvent.change(screen.getByLabelText("Токен оператора"), {
    target: { value: "test-token" },
  });
  await userEvent.click(screen.getByRole("button", { name: "Войти" }));
}

export function mount() {
  return render(
    <MemoryRouter future={{ v7_startTransition: true, v7_relativeSplatPath: true }}>
      <App />
    </MemoryRouter>,
  );
}
