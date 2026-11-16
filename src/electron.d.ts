export {}

declare global {
  interface Window {
    haruka: {
      backendInfo: () => Promise<{
        baseUrl: string
        token: string
        outputRoot: string
        health: unknown
      }>
      restartBackend: () => Promise<unknown>
      runtimeSettings: () => Promise<{ settings: import('./types').RuntimeSettings; lightweight: boolean; configPath: string }>
      discoverRuntime: () => Promise<import('./types').RuntimeDiscovery>
      checkRuntime: (settings: import('./types').RuntimeSettings) => Promise<import('./types').RuntimeReport>
      applyRuntime: (settings: import('./types').RuntimeSettings) => Promise<import('./types').RuntimeReport>
      chooseDirectory: (title?: string) => Promise<string | null>
      chooseFile: (options?: {
        title?: string
        filters?: { name: string; extensions: string[] }[]
      }) => Promise<string | null>
      chooseFiles: (options?: { title?: string; filters?: { name: string; extensions: string[] }[] }) => Promise<string[]>
      revealInFolder: (targetPath: string) => Promise<boolean>
      openDir: (dirPath: string) => Promise<boolean>
      filePath: (file: File) => string
      saveAudio: (name: string, bytes: ArrayBuffer) => Promise<string | null>
    }
  }
}
