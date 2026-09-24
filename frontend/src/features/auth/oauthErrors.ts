/** Human text for `/login?error=<code>` after a Google round trip. */
export const OAUTH_ERRORS: Record<string, string> = {
  google_disabled: 'Google sign-in is not set up on this server yet. Use your email and password.',
  google_cancelled: 'Google sign-in was cancelled.',
  google_expired: 'That sign-in attempt expired or was interrupted. Please try again.',
  google_failed: 'Google sign-in failed. Please try again.',
  google_exchange_failed: 'Google sign-in failed. Please try again.',
  google_unreachable: 'Could not reach Google. Check your connection and try again.',
  google_email_unverified: 'Your Google account email is not verified, so it cannot be used here.',
  google_account_mismatch: 'This email is already linked to a different Google account.',
  google_retry: 'Something went wrong while creating your account. Please try again.',
  registration_closed:
    'There is no account for that Google email and sign-ups are closed. Ask an admin to add you.',
  account_disabled: 'This account has been deactivated. Contact an administrator.',
}
