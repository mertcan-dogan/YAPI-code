import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ExtractionConfidenceBadge } from "./ExtractionConfidenceBadge";

describe("ExtractionConfidenceBadge", () => {
  // CR-024: manual / standard-Excel rows have no score — the badge renders nothing
  // so those rows look untouched (graceful fallback).
  it("renders nothing when confidence is null / undefined / blank / non-numeric", () => {
    const { container, rerender } = render(<ExtractionConfidenceBadge confidence={null} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ExtractionConfidenceBadge confidence={undefined} />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ExtractionConfidenceBadge confidence="" />);
    expect(container).toBeEmptyDOMElement();
    rerender(<ExtractionConfidenceBadge confidence="abc" />);
    expect(container).toBeEmptyDOMElement();
  });

  it("shows the score as a rounded percentage with the AI marker", () => {
    render(<ExtractionConfidenceBadge confidence={0.91} />);
    expect(screen.getByText("AI %91")).toBeInTheDocument();
  });

  it("accepts a numeric string and rounds it", () => {
    render(<ExtractionConfidenceBadge confidence="0.836" />);
    expect(screen.getByText("AI %84")).toBeInTheDocument();
  });

  it("clamps out-of-range values into 0..100", () => {
    const { rerender } = render(<ExtractionConfidenceBadge confidence={1.4} />);
    expect(screen.getByText("AI %100")).toBeInTheDocument();
    rerender(<ExtractionConfidenceBadge confidence={-0.2} />);
    expect(screen.getByText("AI %0")).toBeInTheDocument();
  });

  it("bands the Turkish label by confidence and exposes it via the tooltip", () => {
    const { rerender } = render(<ExtractionConfidenceBadge confidence={0.95} showLabel />);
    expect(screen.getByText(/Yüksek güven/)).toBeInTheDocument();
    expect(screen.getByLabelText(/güveni %95/)).toBeInTheDocument();

    rerender(<ExtractionConfidenceBadge confidence={0.7} showLabel />);
    expect(screen.getByText(/Orta güven/)).toBeInTheDocument();

    rerender(<ExtractionConfidenceBadge confidence={0.3} showLabel />);
    expect(screen.getByText(/Düşük güven/)).toBeInTheDocument();
  });
});
