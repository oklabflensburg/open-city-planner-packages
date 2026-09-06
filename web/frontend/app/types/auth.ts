export interface AuthUser {
  id: string;
  email: string;
  first_name: string;
  last_name: string;
  display_name: string | null;
  is_verified: boolean;
  email_pending: boolean;
}
export interface AuthResponse {
  status: "authenticated";
  user: AuthUser;
  csrf_token: string;
}
export interface MfaChallenge {
  status: "mfa_required";
  challenge_token?: string;
  methods: string[];
  preferred_method: string;
  expires_in: number;
}
export interface Passkey {
  id: string;
  name: string;
  created_at: string;
  last_used_at: string | null;
}
export interface ProviderAccount {
  id: string;
  provider: string;
  provider_username: string | null;
}
export interface MfaStatus {
  enabled: boolean;
  recovery_codes_remaining: number;
}
