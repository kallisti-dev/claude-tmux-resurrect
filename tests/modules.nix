{
  pkgs,
  home-manager,
  nixpkgs,
  module,
  package,
}:
let
  inherit (pkgs) lib;
  fakeClaude = pkgs.writeShellScriptBin "claude" "exit 0";
  overridePackage = package.overrideAttrs (_: {
    pname = "claude-tmux-resurrect-module-test";
  });
  homeDirectory =
    if pkgs.stdenv.hostPlatform.isDarwin then "/Users/module-test" else "/home/module-test";
  evaluate =
    extra:
    (home-manager.lib.homeManagerConfiguration {
      inherit pkgs;
      modules = [
        module
        {
          home = {
            username = "module-test";
            inherit homeDirectory;
            stateVersion = "24.11";
          };
          programs.claude-code.package = fakeClaude;
        }
        extra
      ];
    }).config;
  disabled = evaluate { };
  enabled = evaluate {
    programs.claude-tmux-resurrect.enable = true;
  };
  overridden = evaluate {
    programs.claude-tmux-resurrect = {
      enable = true;
      package = overridePackage;
    };
  };
  previousHook = {
    matcher = "";
    hooks = [
      {
        type = "command";
        command = "existing-claude-hook";
      }
    ];
  };
  customConfigDir = "${homeDirectory}/Claude settings";
  coexist = evaluate {
    programs.claude-tmux-resurrect.enable = true;
    programs.claude-code = {
      configDir = customConfigDir;
      settings = {
        permissions.allow = [ "Read" ];
        hooks = {
          SessionStart = [ previousHook ];
          SessionEnd = [ previousHook ];
        };
      };
    };
    programs.tmux = {
      plugins = [
        {
          plugin = pkgs.tmuxPlugins.yank;
          extraConfig = "set -g @yank_selection 'clipboard'";
        }
      ];
      extraConfig = "set -g @resurrect-hook-post-save-layout 'existing-save-hook'";
    };
  };
  nixosHomes =
    (nixpkgs.lib.nixosSystem {
      inherit (pkgs.stdenv.hostPlatform) system;
      modules = [
        home-manager.nixosModules.home-manager
        {
          nixpkgs.pkgs = pkgs;
          system.stateVersion = "26.05";
          users.users = {
            enabled.isNormalUser = true;
            disabled.isNormalUser = true;
          };
          home-manager = {
            useGlobalPkgs = true;
            sharedModules = [ module ];
            users = {
              enabled = {
                home.stateVersion = "24.11";
                programs.claude-code.package = fakeClaude;
                programs.claude-tmux-resurrect.enable = true;
              };
              disabled.home.stateVersion = "24.11";
            };
          };
        }
      ];
    }).config.home-manager.users;
  hasPackage = config: expected: lib.any (p: p.drvPath == expected.drvPath) config.home.packages;
  hookCommands =
    config: event:
    lib.concatMap (
      entry: map (hook: hook.command) entry.hooks
    ) config.programs.claude-code.settings.hooks.${event};
  integrationHook = expected: "${expected}/bin/claude-tmux-resurrect-hook";
  settingsSource =
    config: config.home.file."${config.programs.claude-code.configDir}/settings.json".source;
  defaultTmuxConfig =
    pkgs.writeText "claude-tmux-default.conf"
      enabled.xdg.configFile."tmux/tmux.conf".text;
  customTmuxConfig =
    pkgs.writeText "claude-tmux-custom.conf"
      coexist.xdg.configFile."tmux/tmux.conf".text;
  check = condition: message: lib.assertMsg condition "Home Manager module: ${message}";
  contains = needle: haystack: lib.hasInfix (builtins.unsafeDiscardStringContext needle) haystack;
  assertions = [
    (check (!disabled.programs.claude-tmux-resurrect.enable) "must be disabled by default")
    (check (!disabled.programs.tmux.enable) "must leave tmux disabled by default")
    (check (!disabled.programs.claude-code.enable) "must leave Claude Code disabled by default")
    (check (disabled.programs.claude-code.settings == { }) "must not add disabled Claude settings")
    (check (!hasPackage disabled package) "must not install its package when disabled")
    (check (disabled.programs.tmux.extraConfig == "") "must not add disabled tmux configuration")
    (check enabled.programs.tmux.enable "must enable tmux")
    (check enabled.programs.claude-code.enable "must enable Claude Code")
    (check (hasPackage enabled package) "must install the default package")
    (check (enabled.programs.claude-code.package == fakeClaude) "must preserve the Claude Code package")
    (check (hasPackage overridden overridePackage) "must install the package override")
    (check (!hasPackage overridden package) "must replace the default package when overridden")
    (check (contains "${overridePackage}/bin/claude-tmux-resurrect-setup" overridden.programs.tmux.extraConfig) "must use the package override for setup")
    (check (
      coexist.programs.tmux.plugins == [
        pkgs.tmuxPlugins.resurrect
        {
          plugin = pkgs.tmuxPlugins.yank;
          extraConfig = "set -g @yank_selection 'clipboard'";
        }
      ]
    ) "must preserve other plugins and their configuration")
    (check (lib.hasPrefix "set -g @resurrect-hook-post-save-layout 'existing-save-hook'" coexist.programs.tmux.extraConfig) "must run setup after existing tmux configuration")
    (check (
      coexist.home.sessionVariables.CLAUDE_CONFIG_DIR == customConfigDir
    ) "must preserve the custom Claude configuration directory")
    (check (contains "set-environment -g CLAUDE_CONFIG_DIR ${lib.escapeShellArg customConfigDir}"
      coexist.xdg.configFile."tmux/tmux.conf".text
    ) "must pass the custom Claude configuration directory to tmux")
    (check (
      !lib.hasInfix "set-environment -g CLAUDE_CONFIG_DIR" enabled.xdg.configFile."tmux/tmux.conf".text
      && lib.hasInfix "set-environment -gu CLAUDE_CONFIG_DIR" enabled.xdg.configFile."tmux/tmux.conf".text
    ) "must unset CLAUDE_CONFIG_DIR for the default Claude configuration directory")
  ]
  ++
    lib.concatMap
      (event: [
        (check (hookCommands enabled event == [ (integrationHook package) ]) "must register ${event} once")
        (check (
          hookCommands overridden event == [ (integrationHook overridePackage) ]
        ) "must use the package override for ${event}")
        (check (
          hookCommands coexist event == [
            "existing-claude-hook"
            (integrationHook package)
          ]
        ) "must preserve existing ${event} hooks before its own")
      ])
      [
        "SessionStart"
        "SessionEnd"
      ]
  ++
    map
      (
        config:
        check (lib.all (
          assertion: assertion.assertion
        ) config.assertions) "configuration assertions must pass"
      )
      [
        disabled
        enabled
        overridden
        coexist
      ]
  ++ lib.optionals pkgs.stdenv.hostPlatform.isLinux [
    (check (
      nixosHomes.enabled.programs.claude-tmux-resurrect.enable
      && nixosHomes.enabled.programs.tmux.enable
      && nixosHomes.enabled.programs.claude-code.enable
    ) "must support an enabled user through NixOS sharedModules")
    (check (hasPackage nixosHomes.enabled package) "must install the package for the enabled NixOS user")
    (check (
      hookCommands nixosHomes.enabled "SessionStart" == [ (integrationHook package) ]
      && hookCommands nixosHomes.enabled "SessionEnd" == [ (integrationHook package) ]
    ) "must configure both hooks for the enabled NixOS user")
    (check (
      !nixosHomes.disabled.programs.claude-tmux-resurrect.enable
      && !nixosHomes.disabled.programs.tmux.enable
      && !nixosHomes.disabled.programs.claude-code.enable
      && !hasPackage nixosHomes.disabled package
    ) "must leave other NixOS users disabled")
    (check (
      lib.all (assertion: assertion.assertion) nixosHomes.enabled.assertions
      && lib.all (assertion: assertion.assertion) nixosHomes.disabled.assertions
    ) "NixOS Home Manager assertions must pass")
  ];
in
assert lib.all (assertion: assertion) assertions;
pkgs.runCommand "home-manager-module"
  {
    nativeBuildInputs = [
      pkgs.jq
      pkgs.tmux
      pkgs.gnugrep
      fakeClaude
    ];
  }
  ''
    jq -e --arg command ${lib.escapeShellArg (integrationHook package)} '
      .hooks.SessionStart[0].hooks[0].command == $command and
      .hooks.SessionEnd[0].hooks[0].command == $command
    ' ${settingsSource enabled} >/dev/null
    jq -e --arg command ${lib.escapeShellArg (integrationHook package)} '
      .permissions.allow == ["Read"] and
      .hooks.SessionStart[0].hooks[0].command == "existing-claude-hook" and
      .hooks.SessionStart[1].hooks[0].command == $command and
      .hooks.SessionEnd[0].hooks[0].command == "existing-claude-hook" and
      .hooks.SessionEnd[1].hooks[0].command == $command
    ' ${settingsSource coexist} >/dev/null

    cp ${defaultTmuxConfig} "$TMPDIR/default.conf"
    cp ${customTmuxConfig} "$TMPDIR/custom.conf"
    chmod u+w "$TMPDIR/default.conf" "$TMPDIR/custom.conf"
    # Darwin's sandbox cannot execute /usr/bin/env from the upstream plugins.
    # Patch disposable copies and substitute only their store paths below.
    ${lib.concatMapStringsSep "\n"
      (name: ''
        cp -R ${pkgs.tmuxPlugins.${name}} "$TMPDIR/${name}"
        chmod -R u+w "$TMPDIR/${name}"
        patchShebangs --build "$TMPDIR/${name}"
      '')
      [
        "resurrect"
        "yank"
      ]
    }
    substituteInPlace "$TMPDIR/default.conf" \
      --replace-fail '${pkgs.tmuxPlugins.resurrect}' "$TMPDIR/resurrect"
    substituteInPlace "$TMPDIR/custom.conf" \
      --replace-fail '${pkgs.tmuxPlugins.resurrect}' "$TMPDIR/resurrect" \
      --replace-fail '${pkgs.tmuxPlugins.yank}' "$TMPDIR/yank"
    for configuration in "$TMPDIR/default.conf" "$TMPDIR/custom.conf"; do
      printf '\nwait-for -S claude-tmux-module-config-loaded\n' >> "$configuration"
    done

    export HOME="$TMPDIR/home"
    mkdir -p "$HOME"
    unset CLAUDE_CONFIG_DIR TMUX
    socket_dir=$(mktemp -d /tmp/claude-tmux-module.XXXXXX)
    socket="$socket_dir/tmux.sock"
    cleanup() {
      tmux -S "$socket" kill-server >/dev/null 2>&1 || true
      rm -rf "$socket_dir"
    }
    trap cleanup EXIT
    cat > "$TMPDIR/startup.conf" <<'EOF'
    set -g default-shell ${pkgs.bash}/bin/bash
    set -g default-command '${pkgs.bash}/bin/bash --noprofile --norc'
    EOF
    tmux -S "$socket" -f "$TMPDIR/startup.conf" new-session -d -s module-test

    load_config() {
      local output
      output=$(tmux -S "$socket" source-file "$1" 2>&1)
      timeout 10 tmux -S "$socket" wait-for claude-tmux-module-config-loaded
      if [[ -n $output ]]; then
        printf '%s\n' "$output" >&2
        return 1
      fi
    }
    load_config "$TMPDIR/default.conf"
    save_bindings=$(tmux -S "$socket" list-keys -T prefix)
    if [[ $save_bindings != *'/tmux-plugins/resurrect/scripts/save.sh'* ]]; then
      printf 'Missing resurrect save binding: %s\n' "$save_bindings" >&2
      exit 1
    fi
    if tmux -S "$socket" show-environment -g CLAUDE_CONFIG_DIR >/dev/null 2>&1; then
      echo 'The default configuration unexpectedly set CLAUDE_CONFIG_DIR' >&2
      exit 1
    fi
    [[ $(tmux -S "$socket" show-options -gqv @resurrect-hook-post-save-layout) == \
      *'${package}/bin/claude-tmux-resurrect-save'* ]]
    for event in client-attached client-session-changed; do
      [[ $(tmux -S "$socket" show-hooks -g "$event" | grep -cF claude-tmux-resurrect-arm) == 1 ]]
    done

    load_config "$TMPDIR/custom.conf"
    tmux -S "$socket" list-keys -T copy-mode-vi | grep -F copy-pipe >/dev/null
    [[ $(tmux -S "$socket" show-environment -g CLAUDE_CONFIG_DIR) == \
      ${lib.escapeShellArg "CLAUDE_CONFIG_DIR=${customConfigDir}"} ]]
    [[ $(tmux -S "$socket" show-options -gqv @claude-tmux-resurrect-previous-post-save-layout) == \
      existing-save-hook ]]
    managed_save=$(tmux -S "$socket" show-options -gqv @resurrect-hook-post-save-layout)
    attached_hook=$(tmux -S "$socket" show-hooks -g client-attached)
    changed_hook=$(tmux -S "$socket" show-hooks -g client-session-changed)

    for reload in 1 2; do
      load_config "$TMPDIR/default.conf"
      if tmux -S "$socket" show-environment -g CLAUDE_CONFIG_DIR >/dev/null 2>&1; then
        echo 'Reloading the default configuration retained CLAUDE_CONFIG_DIR' >&2
        exit 1
      fi
      [[ $(tmux -S "$socket" show-options -gqv @resurrect-hook-post-save-layout) == "$managed_save" ]]
      [[ $(tmux -S "$socket" show-hooks -g client-attached) == "$attached_hook" ]]
      [[ $(tmux -S "$socket" show-hooks -g client-session-changed) == "$changed_hook" ]]
    done
    touch "$out"
  ''
