import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { FrontendApplicationStateService } from '@theia/core/lib/browser/frontend-application-state';
import { OS, PreferenceService } from '@theia/core/lib/common';
import { inject, injectable } from '@theia/core/shared/inversify';
import { TerminalService } from '@theia/terminal/lib/browser/base/terminal-service';
import { ShellTerminalProfile } from '@theia/terminal/lib/browser/shell-terminal-profile';
import {
    TerminalProfileService,
    TerminalProfileStore,
    UserTerminalProfileStore,
} from '@theia/terminal/lib/browser/terminal-profile-service';

const REMOTE_PROFILE = 'ResearchAssistant SSH';

interface ConfiguredTerminalProfile {
    path?: string | string[];
    args?: string[];
    overrideName?: boolean;
}

@injectable()
export class ResearchAssistantRemoteTerminalContribution implements FrontendApplicationContribution {
    @inject(PreferenceService)
    protected readonly preferences: PreferenceService;

    @inject(FrontendApplicationStateService)
    protected readonly applicationState: FrontendApplicationStateService;

    @inject(TerminalService)
    protected readonly terminalService: TerminalService;

    @inject(TerminalProfileService)
    protected readonly profileService: TerminalProfileService;

    @inject(UserTerminalProfileStore)
    protected readonly userProfiles: TerminalProfileStore;

    onStart(): void {
        // Theia awaits every contribution's onStart result before attaching and
        // revealing the workbench shell. Never return the preference/filesystem
        // setup promise here: an unresolved provider would leave the preload
        // spinner visible forever.
        void this.registerAfterFrontendReady();
    }

    protected async registerAfterFrontendReady(): Promise<void> {
        try {
            await this.applicationState.reachedState('ready');
            this.registerConfiguredProfile();
        } catch (error) {
            console.error('Could not register the ResearchAssistant SSH terminal profile', error);
        }
    }

    protected registerConfiguredProfile(): void {
        const profile = this.configuredProfile();
        if (!profile) return;
        const shellPath = this.resolvePath(profile.path);
        if (!shellPath) {
            console.error('ResearchAssistant SSH terminal profile has no wrapper path');
            return;
        }

        this.userProfiles.registerTerminalProfile(
            REMOTE_PROFILE,
            new ShellTerminalProfile(this.terminalService, {
                shellPath,
                shellArgs: profile.args ?? [],
                title: REMOTE_PROFILE,
                useServerTitle: profile.overrideName ? false : undefined,
            }),
        );
        this.profileService.setDefaultProfile(REMOTE_PROFILE);
    }

    protected configuredProfile(): ConfiguredTerminalProfile | undefined {
        let key: string;
        switch (OS.backend.type()) {
            case OS.Type.Linux:
                key = 'terminal.integrated.profiles.linux';
                break;
            case OS.Type.OSX:
                key = 'terminal.integrated.profiles.osx';
                break;
            default:
                return undefined;
        }
        const profiles = this.preferences.get<Record<string, ConfiguredTerminalProfile | null>>(key);
        const profile = profiles?.[REMOTE_PROFILE];
        return profile || undefined;
    }

    protected resolvePath(value: string | string[] | undefined): string | undefined {
        const candidates = typeof value === 'string' ? [value] : value ?? [];
        return candidates.map(candidate => candidate.trim()).find(Boolean);
    }
}
