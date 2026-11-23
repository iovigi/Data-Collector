import React from "react";
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { ErrorState, PermissionDenied, StatCard } from "@/components/ui/primitives";
import { ApiError } from "@/lib/api/errors";

describe("UI primitives", () => {
  it("renders formatted StatCard numbers", () => {
    render(<StatCard label="Active Records" value={12500} />);
    expect(screen.getByText("12,500")).toBeInTheDocument();
  });

  it("renders PermissionDenied on 403 ApiError", () => {
    const err = new ApiError({ status: 403, code: "FORBIDDEN", message: "No key access" });
    render(<ErrorState error={err} />);
    expect(screen.getByText("Access Restricted")).toBeInTheDocument();
    expect(screen.getByText("No key access")).toBeInTheDocument();
  });

  it("renders PermissionDenied message", () => {
    render(<PermissionDenied title="Denied" message="Owner only" />);
    expect(screen.getByText("Denied")).toBeInTheDocument();
    expect(screen.getByText("Owner only")).toBeInTheDocument();
  });
});
