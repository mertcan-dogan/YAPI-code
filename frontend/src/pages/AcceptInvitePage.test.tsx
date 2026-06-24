// CR-041: the accept-invite page resolves an invite token to a preview, then
// signs the invitee up (or in) and accepts — attaching them to the inviting
// company. We mock the auth store + API and drive the form.
import { cleanup, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import { MemoryRouter } from "react-router-dom";

const h = vi.hoisted(() => ({
  acceptInvite: vi.fn(() => Promise.resolve()),
  auth: { user: null as any, loading: false },
}));

vi.mock("@/lib/api", () => ({ apiGet: vi.fn() }));
vi.mock("@/store/auth", () => ({
  useAuth: () => ({ ...h.auth, acceptInvite: h.acceptInvite }),
}));
vi.mock("@/store/toast", () => ({ toast: { success: vi.fn(), error: vi.fn(), info: vi.fn() } }));

import { apiGet } from "@/lib/api";
import AcceptInvitePage from "./AcceptInvitePage";

const PREVIEW = { company_name: "Şirket A", email: "joiner@a.com", role: "finance" };

function renderAt(token = "tok123") {
  return render(
    <MemoryRouter initialEntries={[`/accept-invite?token=${token}`]}>
      <AcceptInvitePage />
    </MemoryRouter>
  );
}

beforeEach(() => {
  vi.clearAllMocks();
  h.auth = { user: null, loading: false };
  (apiGet as any).mockResolvedValue({ data: PREVIEW });
});
afterEach(cleanup);

it("renders the invite preview (company + role) and the signup button", async () => {
  renderAt();
  expect(await screen.findByText("Şirket A")).toBeInTheDocument();
  expect(screen.getByText("Muhasebe")).toBeInTheDocument(); // ROLE_LABELS[finance]
  // Email is pre-filled and read-only.
  const email = screen.getByLabelText("E-posta") as HTMLInputElement;
  expect(email.value).toBe("joiner@a.com");
  expect(email).toHaveAttribute("readonly");
  expect(screen.getByRole("button", { name: "Hesap Oluştur ve Katıl" })).toBeInTheDocument();
});

it("shows an error state for an invalid/expired token", async () => {
  (apiGet as any).mockRejectedValue(new Error("Davet bulunamadı veya süresi dolmuş"));
  renderAt();
  expect(await screen.findByText(/Davet bulunamadı veya süresi dolmuş/)).toBeInTheDocument();
  expect(screen.getByText("Giriş sayfasına dön")).toBeInTheDocument();
});

it("treats a missing token as invalid without calling the API", async () => {
  renderAt("");
  expect(await screen.findByText(/Davet bağlantısı geçersiz/)).toBeInTheDocument();
  expect(apiGet).not.toHaveBeenCalled();
});

it("submits acceptInvite with the invite email, name, password and signup mode", async () => {
  renderAt();
  await screen.findByText("Şirket A");
  fireEvent.change(screen.getByLabelText(/Ad Soyad/), { target: { value: "Yeni Üye" } });
  fireEvent.change(screen.getByLabelText(/Şifre/), { target: { value: "secret123" } });
  fireEvent.click(screen.getByRole("button", { name: "Hesap Oluştur ve Katıl" }));
  await waitFor(() =>
    expect(h.acceptInvite).toHaveBeenCalledWith("tok123", "joiner@a.com", "secret123", "Yeni Üye", "signup")
  );
});

it("can switch to sign-in mode for an already-registered invitee", async () => {
  renderAt();
  await screen.findByText("Şirket A");
  fireEvent.click(screen.getByText("Giriş yaparak katılın"));
  expect(screen.getByRole("button", { name: "Giriş Yap ve Katıl" })).toBeInTheDocument();

  fireEvent.change(screen.getByLabelText(/Ad Soyad/), { target: { value: "Yeni Üye" } });
  fireEvent.change(screen.getByLabelText(/Şifre/), { target: { value: "secret123" } });
  fireEvent.click(screen.getByRole("button", { name: "Giriş Yap ve Katıl" }));
  await waitFor(() =>
    expect(h.acceptInvite).toHaveBeenCalledWith("tok123", "joiner@a.com", "secret123", "Yeni Üye", "signin")
  );
});
