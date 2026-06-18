import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

// Hoisted mocks for the api + toast modules the control depends on.
const { apiPostMock, toastErrorMock, toastSuccessMock } = vi.hoisted(() => ({
  apiPostMock: vi.fn(),
  toastErrorMock: vi.fn(),
  toastSuccessMock: vi.fn(),
}));
vi.mock("@/lib/api", () => ({ apiPost: apiPostMock }));
vi.mock("@/store/toast", () => ({ toast: { error: toastErrorMock, success: toastSuccessMock } }));

import { AiFeedbackControl } from "./AiFeedbackControl";

afterEach(() => vi.clearAllMocks());

describe("AiFeedbackControl", () => {
  it("posts the right payload and shows a confirmation", async () => {
    apiPostMock.mockResolvedValue({});
    render(<AiFeedbackControl question="Marj neden düştü?" queryLogId="log-1" />);

    fireEvent.click(screen.getByLabelText("Yararlı"));

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenCalledWith("/ai/agent/feedback", {
        query_log_id: "log-1",
        question: "Marj neden düştü?",
        rating: "up",
        comment: null,
      })
    );
    expect(await screen.findByText(/Teşekkürler/)).toBeInTheDocument();
  });

  it("guards re-submitting the same rating", async () => {
    apiPostMock.mockResolvedValue({});
    render(<AiFeedbackControl question="Q" queryLogId="l" />);
    const up = screen.getByLabelText("Yararlı");

    fireEvent.click(up);
    await waitFor(() => expect(apiPostMock).toHaveBeenCalledTimes(1));
    fireEvent.click(up); // same rating again → must not post twice
    await Promise.resolve();
    expect(apiPostMock).toHaveBeenCalledTimes(1);
  });

  it("degrades to a toast (no crash, no confirmation) when the POST fails", async () => {
    apiPostMock.mockRejectedValue(new Error("network"));
    render(<AiFeedbackControl question="Q" queryLogId="l" />);

    fireEvent.click(screen.getByLabelText("Yararsız"));

    await waitFor(() => expect(toastErrorMock).toHaveBeenCalled());
    expect(screen.queryByText(/Teşekkürler/)).not.toBeInTheDocument();
  });

  it("after 👎 reveals an optional comment box and posts the comment", async () => {
    apiPostMock.mockResolvedValue({});
    render(<AiFeedbackControl question="Q" queryLogId="l" />);

    fireEvent.click(screen.getByLabelText("Yararsız"));
    const box = await screen.findByPlaceholderText("Görüşünüz (isteğe bağlı)");
    fireEvent.change(box, { target: { value: "Yanlış tedarikçi" } });
    fireEvent.click(screen.getByRole("button", { name: "Gönder" }));

    await waitFor(() =>
      expect(apiPostMock).toHaveBeenLastCalledWith("/ai/agent/feedback", {
        query_log_id: "l",
        question: "Q",
        rating: "down",
        comment: "Yanlış tedarikçi",
      })
    );
    expect(toastSuccessMock).toHaveBeenCalled();
  });
});
