{
  pkgs,
  nixpkgs,
  module,
  package,
}:
let
  inherit (pkgs) lib;
  linuxPkgs =
    if pkgs.stdenv.hostPlatform.isLinux then pkgs else import nixpkgs { system = "x86_64-linux"; };
  defaultPackage =
    if pkgs.stdenv.hostPlatform.isLinux then package else linuxPkgs.callPackage ../package.nix { };
  overridePackage = defaultPackage.overrideAttrs (_: {
    pname = "claude-tmux-resurrect-nixos-module-test";
  });
  fakeClaude = linuxPkgs.writeShellScriptBin "claude" "exit 0";
  customClaude = fakeClaude.overrideAttrs (_: {
    version = "2.1.83";
  });
  outdatedClaude = fakeClaude.overrideAttrs (_: {
    version = "2.1.82";
  });
  settingsPath = "claude-code/managed-settings.d/claude-tmux-resurrect.json";
  evaluate =
    extra:
    (nixpkgs.lib.nixosSystem {
      inherit (linuxPkgs.stdenv.hostPlatform) system;
      modules = [
        module
        {
          nixpkgs.pkgs = linuxPkgs;
          boot.isContainer = true;
          system.stateVersion = "26.05";
        }
        extra
      ];
    }).config;
  disabled = evaluate { };
  enabled = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      claudePackage = fakeClaude;
    };
  };
  overridden = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      package = overridePackage;
      claudePackage = customClaude;
    };
  };
  separateClaude = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      claudePackage = null;
    };
  };
  outdated = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      claudePackage = outdatedClaude;
    };
  };
  existingSettings = {
    permissions.allow = [ "Read" ];
    hooks.SessionStart = [
      {
        hooks = [
          {
            type = "command";
            command = "existing-claude-hook";
          }
        ];
      }
    ];
  };
  coexist = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      claudePackage = fakeClaude;
    };
    programs.tmux = {
      plugins = [ linuxPkgs.tmuxPlugins.yank ];
      extraConfig = "set -g @resurrect-hook-post-save-layout 'existing-save-hook'";
    };
    environment.etc."claude-code/managed-settings.d/existing.json".text =
      builtins.toJSON existingSettings;
  };
  hasPackage =
    config: expected: lib.any (p: p.drvPath == expected.drvPath) config.environment.systemPackages;
  contains = needle: haystack: lib.hasInfix (builtins.unsafeDiscardStringContext needle) haystack;
  integrationHook = expected: "${expected}/bin/claude-tmux-resurrect-hook";
  settings =
    config:
    builtins.fromJSON (builtins.unsafeDiscardStringContext config.environment.etc.${settingsPath}.text);
  hookCommands =
    config: event:
    lib.concatMap (entry: map (hook: hook.command) entry.hooks) (settings config).hooks.${event};
  check = condition: message: lib.assertMsg condition "NixOS module: ${message}";
  assertions = [
    (check (!disabled.programs.claude-tmux-resurrect.enable) "must be disabled by default")
    (check (!disabled.programs.tmux.enable) "must leave tmux disabled by default")
    (check (
      disabled.programs.claude-tmux-resurrect.claudePackage.pname == "claude-code"
    ) "must default to the nixpkgs Claude Code package")
    (check (!hasPackage disabled defaultPackage) "must not install the integration when disabled")
    (check (
      !builtins.hasAttr settingsPath disabled.environment.etc
    ) "must not add disabled managed settings")
    (check (disabled.programs.tmux.extraConfig == "") "must not add disabled tmux configuration")
    (check enabled.programs.tmux.enable "must enable tmux")
    (check (hasPackage enabled defaultPackage) "must install the default integration package")
    (check (hasPackage enabled fakeClaude) "must install the configured Claude Code package")
    (check (hasPackage overridden overridePackage) "must install the integration package override")
    (check (!hasPackage overridden defaultPackage) "must replace the default integration package")
    (check (hasPackage overridden customClaude) "must install a custom Claude Code package")
    (check (!hasPackage overridden fakeClaude) "must replace the previous Claude Code package")
    (check (contains "${overridePackage}/bin/claude-tmux-resurrect-setup" overridden.programs.tmux.extraConfig) "must use the integration override for setup")
    (check (hasPackage separateClaude defaultPackage) "must install the integration with separately installed Claude Code")
    (check (
      separateClaude.programs.claude-tmux-resurrect.claudePackage == null
    ) "must accept separately installed Claude Code")
    (check (lib.any (
      assertion: !assertion.assertion && lib.hasInfix "Claude Code 2.1.83" assertion.message
    ) outdated.assertions) "must reject Claude Code without managed settings fragment support")
    (check (
      coexist.programs.tmux.plugins == [
        linuxPkgs.tmuxPlugins.resurrect
        linuxPkgs.tmuxPlugins.yank
      ]
    ) "must preserve other tmux plugins")
    (check (lib.hasPrefix "set -g @resurrect-hook-post-save-layout 'existing-save-hook'" coexist.programs.tmux.extraConfig) "must run setup after existing tmux configuration")
    (check (
      builtins.fromJSON coexist.environment.etc."claude-code/managed-settings.d/existing.json".text
      == existingSettings
    ) "must preserve other managed settings files")
  ]
  ++
    lib.concatMap
      (event: [
        (check (
          hookCommands enabled event == [ (integrationHook defaultPackage) ]
        ) "must register ${event} once")
        (check (
          hookCommands overridden event == [ (integrationHook overridePackage) ]
        ) "must use the integration override for ${event}")
        (check (
          hookCommands coexist event == [ (integrationHook defaultPackage) ]
        ) "must register ${event} alongside other managed settings")
      ])
      [
        "SessionStart"
        "SessionEnd"
      ]
  ++
    lib.concatMap
      (config: [
        (check (
          !builtins.hasAttr "CLAUDE_CONFIG_DIR" config.environment.variables
        ) "must preserve per-user Claude configuration directories")
        (check (
          !builtins.hasAttr "CLAUDE_CONFIG_DIR" config.environment.sessionVariables
        ) "must not set a shared Claude configuration directory")
        (check (lib.all (
          assertion: assertion.assertion
        ) config.assertions) "NixOS configuration assertions must pass")
      ])
      [
        disabled
        enabled
        overridden
        separateClaude
        coexist
      ];
  # Evaluate real Linux modules on Darwin without building Linux derivations.
  settingsSource =
    config:
    pkgs.writeText "nixos-managed-settings.json" (
      builtins.unsafeDiscardStringContext config.environment.etc.${settingsPath}.text
    );
in
assert lib.all (assertion: assertion) assertions;
pkgs.runCommand "nixos-module" { nativeBuildInputs = [ pkgs.jq ]; } ''
  jq -e --arg command ${lib.escapeShellArg (builtins.unsafeDiscardStringContext (integrationHook defaultPackage))} '
    (.hooks | keys) == ["SessionEnd", "SessionStart"] and
    (.hooks.SessionStart | length) == 1 and
    (.hooks.SessionEnd | length) == 1 and
    .hooks.SessionStart[0].hooks == [{"type": "command", "command": $command}] and
    .hooks.SessionEnd[0].hooks == [{"type": "command", "command": $command}]
  ' ${settingsSource enabled} >/dev/null
  jq -e --arg command ${lib.escapeShellArg (builtins.unsafeDiscardStringContext (integrationHook overridePackage))} '
    .hooks.SessionStart[0].hooks[0].command == $command and
    .hooks.SessionEnd[0].hooks[0].command == $command
  ' ${settingsSource overridden} >/dev/null
  touch "$out"
''
