import React from "react";
import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import { CountBadge } from "@/components/data/CountBadge";
import { JsonTree } from "@/components/data/JsonTree";

describe("CountBadge", () => {
  it("renders pending and unavailable without displaying zero", () => {
    const { rerender } = render(<CountBadge bucket={null} />);
    expect(screen.getByText(/Pending/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();

    rerender(
      <CountBadge
        bucket={{
          value: null,
          accuracy: "unavailable",
          as_of: null,
          age_seconds: null,
          source: "planner",
          reason: "timed out",
        }}
      />
    );
    expect(screen.getByText(/Unavailable/i)).toBeInTheDocument();
    expect(screen.queryByText("0")).not.toBeInTheDocument();
  });

  it("renders formatted exact_as_of count with freshness label", () => {
    render(
      <CountBadge
        bucket={{
          value: 1234567,
          accuracy: "exact_as_of",
          as_of: "2026-11-28T00:00:00Z",
          age_seconds: 12,
          source: "cache",
        }}
      />
    );
    expect(screen.getByText(/1,234,567/)).toBeInTheDocument();
    expect(screen.getByText(/exact/)).toBeInTheDocument();
  });
});

describe("JsonTree", () => {
  it("escapes HTML/script payloads and chunks huge arrays", () => {
    const huge = Array.from({ length: 10_000 }, (_, i) => i);
    render(
      <JsonTree
        data={{
          xss: '<script>alert("xss")</script>',
          huge,
        }}
        initialExpandDepth={3}
      />
    );
    expect(screen.getByText(/<script>alert\("xss"\)<\/script>/)).toBeInTheDocument();
    expect(screen.getByText(/\[10,000 items\]/)).toBeInTheDocument();
    // Only first 50 items should be rendered initially, not 10,000 DOM nodes.
    expect(screen.getByText("[0]")).toBeInTheDocument();
    expect(screen.getByText("[49]")).toBeInTheDocument();
    expect(screen.queryByText("[50]")).not.toBeInTheDocument();
    expect(screen.getByRole("button", { name: /Show next 50 of 9,950/i })).toBeInTheDocument();
  });
});
