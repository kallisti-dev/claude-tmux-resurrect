{
  pkgs,
  nixpkgs,
  nix-darwin,
  module,
  package,
}:
let
  inherit (pkgs) lib;
  darwinPkgs =
    if pkgs.stdenv.hostPlatform.isDarwin then pkgs else import nixpkgs { system = "aarch64-darwin"; };
  defaultPackage =
    if pkgs.stdenv.hostPlatform.isDarwin then package else darwinPkgs.callPackage ../package.nix { };
  overridePackage = defaultPackage.overrideAttrs (_: {
    pname = "claude-tmux-resurrect-darwin-module-test";
  });
  fakeClaude = darwinPkgs.writeShellScriptBin "claude" "exit 0";
  customClaude = fakeClaude.overrideAttrs (_: {
    version = "2.1.83";
  });
  outdatedClaude = fakeClaude.overrideAttrs (_: {
    version = "2.1.82";
  });
  settingsPath = "claude-code/managed-settings.d/claude-tmux-resurrect.json";
  managedDirectory = "/Library/Application Support/ClaudeCode/managed-settings.d";
  settingsTarget = "/etc/${settingsPath}";
  evaluate =
    extra:
    (nix-darwin.lib.darwinSystem {
      modules = [
        module
        {
          nixpkgs.pkgs = darwinPkgs;
          system.stateVersion = 6;
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
  };
  existingTmux = "set -g @resurrect-hook-post-save-layout 'existing-save-hook'";
  coexist = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      claudePackage = fakeClaude;
    };
    programs.tmux.extraConfig = existingTmux;
    environment.etc."claude-code/managed-settings.d/existing.json".text =
      builtins.toJSON existingSettings;
    environment.etc."claude-code/managed-settings.json".text = builtins.toJSON existingSettings;
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
  check = condition: message: lib.assertMsg condition "nix-darwin module: ${message}";
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
    (check (hasPackage enabled fakeClaude) "must accept a Claude Code package without a known version")
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
    (check (lib.hasPrefix existingTmux coexist.programs.tmux.extraConfig) "must preserve existing tmux configuration before integration setup")
    (check (contains "run-shell '${darwinPkgs.tmuxPlugins.resurrect.rtp}'" enabled.programs.tmux.extraConfig) "must load tmux-resurrect")
    (check (contains "run-shell '${darwinPkgs.tmuxPlugins.resurrect.rtp}'\nrun-shell '${defaultPackage}/bin/claude-tmux-resurrect-setup'" enabled.programs.tmux.extraConfig) "must load tmux-resurrect before setup")
    (check (
      builtins.fromJSON coexist.environment.etc."claude-code/managed-settings.d/existing.json".text
      == existingSettings
    ) "must preserve other managed settings files")
    (check (
      !builtins.hasAttr "claude-code/managed-settings.json" enabled.environment.etc
    ) "must keep the main managed settings file available for other policy")
    (check (
      builtins.fromJSON coexist.environment.etc."claude-code/managed-settings.json".text
      == existingSettings
    ) "must preserve the main managed settings file")
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
        (check (lib.all (
          assertion: assertion.assertion
        ) config.assertions) "nix-darwin configuration assertions must pass")
      ])
      [
        disabled
        enabled
        overridden
        separateClaude
        coexist
      ];
  settingsSource =
    config:
    pkgs.writeText "darwin-managed-settings.json" (
      builtins.unsafeDiscardStringContext config.environment.etc.${settingsPath}.text
    );
  activationSource =
    config:
    pkgs.writeText "darwin-managed-settings-activation.sh" (
      builtins.unsafeDiscardStringContext config.system.activationScripts.postActivation.text
    );
in
assert lib.all (assertion: assertion) assertions;
pkgs.runCommand "darwin-module" { nativeBuildInputs = [ pkgs.jq ]; } ''
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

  policyDir="$TMPDIR/Library/Application Support/ClaudeCode/managed-settings.d"
  backingFile="$TMPDIR/etc/claude-code/managed-settings.d/claude-tmux-resurrect.json"
  managedFile="$policyDir/claude-tmux-resurrect.json"
  mkdir -p "$(dirname "$backingFile")"
  cp ${settingsSource enabled} "$backingFile"
  substitute ${activationSource enabled} "$TMPDIR/enable.sh" \
    --replace-fail ${lib.escapeShellArg managedDirectory} "$policyDir" \
    --replace-fail ${lib.escapeShellArg settingsTarget} "$backingFile"
  substitute ${activationSource disabled} "$TMPDIR/disable.sh" \
    --replace-fail ${lib.escapeShellArg managedDirectory} "$policyDir" \
    --replace-fail ${lib.escapeShellArg settingsTarget} "$backingFile"

  bash "$TMPDIR/enable.sh"
  test -L "$managedFile"
  test "$(readlink "$managedFile")" = "$backingFile"
  printf '%s\n' '{"permissions":{"allow":["Read"]}}' > "$policyDir/existing.json"
  cp "$policyDir/existing.json" "$TMPDIR/expected-policy.json"
  bash "$TMPDIR/enable.sh"
  cmp "$TMPDIR/expected-policy.json" "$policyDir/existing.json"
  rm "$backingFile"
  bash "$TMPDIR/disable.sh"
  test ! -e "$managedFile" && test ! -L "$managedFile"
  cmp "$TMPDIR/expected-policy.json" "$policyDir/existing.json"
  bash "$TMPDIR/disable.sh"

  cp "$TMPDIR/expected-policy.json" "$managedFile"
  if bash "$TMPDIR/enable.sh"; then
    echo "activation must reject an existing unmanaged settings file" >&2
    exit 1
  fi
  cmp "$TMPDIR/expected-policy.json" "$managedFile"
  bash "$TMPDIR/disable.sh"
  cmp "$TMPDIR/expected-policy.json" "$managedFile"
  rm "$managedFile"

  ln -s "$TMPDIR/missing-policy.json" "$managedFile"
  if bash "$TMPDIR/enable.sh"; then
    echo "activation must reject an existing unmanaged symlink" >&2
    exit 1
  fi
  test "$(readlink "$managedFile")" = "$TMPDIR/missing-policy.json"
  bash "$TMPDIR/disable.sh"
  test "$(readlink "$managedFile")" = "$TMPDIR/missing-policy.json"
  cmp "$TMPDIR/expected-policy.json" "$policyDir/existing.json"
  touch "$out"
''
