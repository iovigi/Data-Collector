/**
 * SPA routing primitives (React Router) with the small API surface the pages use.
 *
 * Replaces `next/navigation` and `next/link` after the move from Next.js server rendering
 * to a client-side SPA served by the Python/IIS host.
 */
import React from "react";
import {
  Link as RRLink,
  useLocation,
  useNavigate,
  useParams as useRRParams,
  useSearchParams as useRRSearchParams,
} from "react-router";

export interface AppRouter {
  push: (href: string) => void;
  replace: (href: string) => void;
  back: () => void;
}

export function useRouter(): AppRouter {
  const navigate = useNavigate();
  return React.useMemo(
    () => ({
      push: (href: string) => navigate(href),
      replace: (href: string) => navigate(href, { replace: true }),
      back: () => navigate(-1),
    }),
    [navigate]
  );
}

export function useParams<T extends Record<string, string>>(): T {
  return useRRParams() as unknown as T;
}

export function usePathname(): string {
  return useLocation().pathname;
}

export function useSearchParams(): URLSearchParams {
  const [params] = useRRSearchParams();
  return params;
}

type LinkProps = Omit<React.AnchorHTMLAttributes<HTMLAnchorElement>, "href"> & {
  href: string;
  replace?: boolean;
};

export function Link({ href, replace, children, ...rest }: LinkProps) {
  return (
    <RRLink to={href} replace={replace} {...rest}>
      {children}
    </RRLink>
  );
}

export default Link;
