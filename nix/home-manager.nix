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
    enable = lib.mkEnableOption "Claude Code session restoration with tmux-resurrect";

    package = lib.mkOption {
      type = lib.types.package;
      default = pkgs.callPackage ../package.nix { };
      defaultText = "The package built from this source with your nixpkgs.";
      description = "The claude-tmux-resurrect package to install and use for hooks.";
    };
  };

  config = lib.mkIf cfg.enable {
    home.packages = [ cfg.package ];

    programs.claude-code = {
      enable = true;
      settings.hooks = {
        SessionStart = lib.mkAfter [ claudeHook ];
        SessionEnd = lib.mkAfter [ claudeHook ];
      };
    };

    programs.tmux = {
      enable = true;
      plugins = lib.mkBefore [ pkgs.tmuxPlugins.resurrect ];
      # The default needs an unset variable, including after reloading a
      # previously custom directory, so Claude still reads ~/.claude.json.
      extraConfig = lib.mkAfter (
        (
          if config.programs.claude-code.configDir != "${config.home.homeDirectory}/.claude" then
            ''
              set-environment -g CLAUDE_CONFIG_DIR ${lib.escapeShellArg config.programs.claude-code.configDir}
            ''
          else
            ''
              set-environment -gu CLAUDE_CONFIG_DIR
            ''
        )
        + ''
          run-shell '${cfg.package}/bin/claude-tmux-resurrect-setup'
        ''
      );
    };
  };
}
