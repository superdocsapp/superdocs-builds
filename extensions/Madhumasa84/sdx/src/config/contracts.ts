export interface Profile {
  readonly name: string;
  readonly baseUrl: URL;
  readonly credentialReference: string;
}

export interface ProfileStore {
  load(name: string): Promise<Profile | undefined>;
  save(profile: Profile): Promise<void>;
}

