const ALLOWED_V1_PATH_PATTERNS: RegExp[] = [
  /^me$/,
  /^openapi\.json$/,
  /^workspaces$/,
  /^workspaces\/[a-f0-9]{24}$/,
  /^workspaces\/[a-f0-9]{24}\/(archive|restore|capabilities|dashboard\/summary|members|invitations|transfer-ownership|projects|jobs|audit|webhooks|usage)$/,
  /^workspaces\/[a-f0-9]{24}\/members\/[a-f0-9]{24}$/,
  /^workspaces\/[a-f0-9]{24}\/webhooks\/[a-f0-9]{24}$/,
  /^workspaces\/[a-f0-9]{24}\/webhooks\/[a-f0-9]{24}\/(rotate-secret|deliveries)$/,
  /^invitations\/[a-f0-9]{24}\/(accept|revoke)$/,
  /^projects\/[a-f0-9]{24}$/,
  /^projects\/[a-f0-9]{24}\/(archive|restore|collections)$/,
  /^collections\/[a-f0-9]{24}$/,
  /^collections\/[a-f0-9]{24}\/(records|records\/batch|records\/search|records\/trash|imports|exports|saved-queries|schema-migrations\/preview|schema-migrations\/apply)$/,
  /^collections\/[a-f0-9]{24}\/records\/[a-f0-9]{24}$/,
  /^collections\/[a-f0-9]{24}\/records\/[a-f0-9]{24}\/restore$/,
  /^saved-queries\/[a-f0-9]{24}$/,
  /^saved-queries\/[a-f0-9]{24}\/run$/,
  /^jobs\/[a-f0-9]{24}$/,
  /^jobs\/[a-f0-9]{24}\/(result|cancel)$/,
  /^keys$/,
  /^keys\/[a-f0-9]{24}\/revoke$/,
  /^audit$/,
];

export function isAllowedBackendPath(joinedPath: string): boolean {
  if (
    !joinedPath ||
    joinedPath.includes("..") ||
    joinedPath.includes("://") ||
    joinedPath.startsWith("/")
  ) {
    return false;
  }
  return ALLOWED_V1_PATH_PATTERNS.some((re) => re.test(joinedPath));
}
