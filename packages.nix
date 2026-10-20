{
  lib,
  stdenvNoCC,
  tmuxPlugins,
  makeWrapper,
  bash,
  tmux,
  jq,
  coreutils,
}:
let
  inherit (lib.importJSON ./.claude-plugin/plugin.json) version;
  # Both plugins read their version from the manifest, and either can run the
  # check and show notices.
  source =
    files:
    lib.fileset.toSource {
      root = ./.;
      fileset = lib.fileset.unions (
        [
          ./.claude-plugin/plugin.json
          ./bin/tmux-agent-resurrect-check
          ./bin/tmux-agent-resurrect-notify
          ./docs
          ./lib
          ./LICENSE.md
        ]
        ++ files
      );
    };
  # tmux and Claude run these scripts by path with their own PATH.
  wrapScripts = scripts: ''
    for script in ${scripts}; do
      wrapProgram "$script" --prefix PATH : ${
        lib.makeBinPath [
          bash
          tmux
          jq
          coreutils
        ]
      }
    done
  '';
  meta = {
    homepage = "https://github.com/kallisti-dev/tmux-agent-resurrect";
    license = lib.licenses.bsd3;
    platforms = [
      "aarch64-darwin"
      "aarch64-linux"
      "x86_64-linux"
    ];
  };
  # A plugin directory that an agent loads, with its wrapped scripts.
  agentPlugin =
    {
      agent,
      files,
      description,
    }:
    stdenvNoCC.mkDerivation {
      pname = "tmux-agent-resurrect-${agent}-plugin";
      inherit version;
      src = source files;
      strictDeps = true;
      nativeBuildInputs = [ makeWrapper ];
      buildInputs = [ bash ];
      dontBuild = true;
      installPhase = ''
        runHook preInstall
        cp -R . "$out"
        ${wrapScripts ''"$out"/bin/*''}
        runHook postInstall
      '';
      meta = meta // {
        inherit description;
      };
    };
in
{
  tmux-plugin = tmuxPlugins.mkTmuxPlugin {
    pluginName = "tmux-agent-resurrect";
    # The default file name replaces hyphens with underscores.
    rtpFilePath = "tmux-agent-resurrect.tmux";
    inherit version;
    # Without the Claude Code hooks, setup leaves CLAUDE_CODE_PLUGIN_DIRS
    # alone and the Claude plugin is installed separately.
    src = source [
      ./tmux-agent-resurrect.tmux
      ./bin/tmux-agent-resurrect-arm
      ./bin/tmux-agent-resurrect-post-restore
      ./bin/tmux-agent-resurrect-pre-restore
      ./bin/tmux-agent-resurrect-save
      ./bin/tmux-agent-resurrect-setup
    ];
    nativeBuildInputs = [ makeWrapper ];
    # mkTmuxPlugin sets strictDeps, so patchShebangs finds bash only here.
    buildInputs = [ bash ];
    postInstall = wrapScripts ''"$out"/share/tmux-plugins/tmux-agent-resurrect/{tmux-agent-resurrect.tmux,bin/*}'';
    meta = meta // {
      description = "tmux plugin that restores Claude Code conversations with tmux-resurrect";
    };
  };

  claude-plugin = agentPlugin {
    agent = "claude";
    files = [
      ./bin/tmux-agent-resurrect-claude-hook
      ./hooks
      ./skills
    ];
    description = "Claude Code plugin with the session hooks for the tmux-agent-resurrect tmux plugin";
  };

  opencode-plugin = agentPlugin {
    agent = "opencode";
    files = [
      ./bin/tmux-agent-resurrect-record
      ./opencode
    ];
    description = "OpenCode plugin that records sessions for the tmux-agent-resurrect tmux plugin";
  };
}
