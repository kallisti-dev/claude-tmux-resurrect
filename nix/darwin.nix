{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.claude-tmux-resurrect;
  settingsFile = "claude-code/managed-settings.d/claude-tmux-resurrect.json";
  settingsDirectory = "/Library/Application Support/ClaudeCode/managed-settings.d";
  claudeHook = {
    hooks = [
      {
        type = "command";
        command = "${cfg.package}/bin/claude-tmux-resurrect-hook";
      }
    ];
  };
in
{
  options.programs.claude-tmux-resurrect = {
    enable = lib.mkEnableOption "system-wide Claude Code session restoration with tmux-resurrect";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../package.nix { };
      defaultText = "The package built from this source with your nixpkgs.";
      description = "The claude-tmux-resurrect package to install and use for hooks.";
    };

    claudePackage = lib.mkPackageOption pkgs "claude-code" {
      nullable = true;
      extraDescription = ''
        Must support managed settings fragments (Claude Code 2.1.83 or newer).
        Set to null to use a separately installed Claude Code.
      '';
    };
  };

  config = lib.mkMerge [
    {
      # Keep cleanup available when the option is disabled. Only the exact
      # symlink owned by this module is removed or accepted on activation.
      system.activationScripts.postActivation.text =
        let
          target = "${settingsDirectory}/claude-tmux-resurrect.json";
          source = "/etc/${settingsFile}";
        in
        if cfg.enable then
          ''
            if [ -L ${lib.escapeShellArg target} ] && [ "$(readlink ${lib.escapeShellArg target})" = ${lib.escapeShellArg source} ]; then
              :
            elif [ -e ${lib.escapeShellArg target} ] || [ -L ${lib.escapeShellArg target} ]; then
              echo "claude-tmux-resurrect: refusing to replace ${target}" >&2
              exit 1
            else
              mkdir -p ${lib.escapeShellArg settingsDirectory}
              ln -s ${lib.escapeShellArg source} ${lib.escapeShellArg target}
            fi
          ''
        else
          ''
            if [ -L ${lib.escapeShellArg target} ] && [ "$(readlink ${lib.escapeShellArg target})" = ${lib.escapeShellArg source} ]; then
              rm ${lib.escapeShellArg target}
            fi
          '';
    }
    (lib.mkIf cfg.enable {
      assertions = [
        {
          assertion =
            cfg.claudePackage == null
            || lib.getVersion cfg.claudePackage == ""
            || lib.versionAtLeast (lib.getVersion cfg.claudePackage) "2.1.83";
          message = "programs.claude-tmux-resurrect requires Claude Code 2.1.83 or newer for managed settings fragments.";
        }
      ];

      environment = {
        systemPackages = [ cfg.package ] ++ lib.optional (cfg.claudePackage != null) cfg.claudePackage;
        etc.${settingsFile}.text = builtins.toJSON {
          hooks = {
            SessionStart = [ claudeHook ];
            SessionEnd = [ claudeHook ];
          };
        };
      };

      programs.tmux = {
        enable = true;
        extraConfig = lib.mkAfter ''
          run-shell '${pkgs.tmuxPlugins.resurrect.rtp}'
          run-shell '${cfg.package}/bin/claude-tmux-resurrect-setup'
        '';
      };
    })
  ];
}
