import { FrontendApplicationContribution } from '@theia/core/lib/browser';
import { OS, PreferenceService } from '@theia/core/lib/common';
import URI from '@theia/core/lib/common/uri';
import { inject, injectable } from '@theia/core/shared/inversify';
import { FileService } from '@theia/filesystem/lib/browser/file-service';
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

    @inject(FileService)
    protected readonly fileService: FileService;

    @inject(TerminalService)
    protected readonly terminalService: TerminalService;

    @inject(TerminalProfileService)
    protected readonly profileService: TerminalProfileService;

    @inject(UserTerminalProfileStore)
    protected readonly userProfiles: TerminalProfileStore;

    async onStart(): Promise<void> {
        await this.preferences.ready;
        const profile = this.configuredProfile();
        if (!profile) return;
        const shellPath = await this.resolvePath(profile.path);
        if (!shellPath) {
            console.error('ResearchAssistant SSH terminal wrapper does not exist');
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

    protected async resolvePath(value: string | string[] | undefined): Promise<string | undefined> {
        const candidates = typeof value === 'string' ? [value] : value ?? [];
        for (const candidate of candidates) {
            const path = candidate.trim();
            if (!path) continue;
            if (await this.fileService.exists(URI.fromFilePath(path))) return path;
        }
        return undefined;
    }
}
