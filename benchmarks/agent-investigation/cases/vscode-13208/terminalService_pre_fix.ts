Source: microsoft/vscode terminalService.ts immediately before the issue was fixed.

export class MacTerminalService implements ITerminalService {
    // ... unrelated code omitted ...

    private _runScript(script: string, args: string[]): TPromise<void> {
        return new TPromise<void>((c, e) => {
            // ... process launch omitted ...
            child.on('close', (code: number) => {
                if (code) {
                    if (stderr) {
                        const lines = stderr.split('\n', 1);
                        e(new Error(lines[0]));
                    } else {
                        e(new Error(nls.localize(
                            'mac.terminal.script.failed',
                            "script '{0}' failed with exit code {1}",
                            script,
                            code
                        )));
                    }
                } else {
                    c(null);
                }
            });
        });
    }
}
