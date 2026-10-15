{
  config,
  lib,
  pkgs,
  ...
}:
let
  cfg = config.programs.claude-tmux-resurrect;
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

  config = lib.mkIf cfg.enable {
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
      etc."claude-code/managed-settings.d/claude-tmux-resurrect.json".text = builtins.toJSON {
        hooks = {
          SessionStart = [ claudeHook ];
          SessionEnd = [ claudeHook ];
        };
      };
    };

    programs.tmux = {
      enable = true;
      plugins = lib.mkBefore [ pkgs.tmuxPlugins.resurrect ];
      extraConfig = lib.mkAfter ''
        run-shell '${cfg.package}/bin/claude-tmux-resurrect-setup'
      '';
    };
  };
}
