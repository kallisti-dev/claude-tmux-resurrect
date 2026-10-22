{
  description = "tmux plugin that restores Claude Code conversations with tmux-resurrect";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    resurrect = {
      url = "github:tmux-plugins/tmux-resurrect";
      flake = false;
    };
    tpm = {
      url = "github:tmux-plugins/tpm";
      flake = false;
    };
    oh-my-tmux = {
      url = "github:gpakosz/.tmux";
      flake = false;
    };
  };

  outputs =
    {
      nixpkgs,
      resurrect,
      tpm,
      oh-my-tmux,
      ...
    }:
    let
      systems = [
        "aarch64-darwin"
        "aarch64-linux"
        "x86_64-linux"
      ];
      eachSystem = nixpkgs.lib.genAttrs systems;
      forSystem =
        system:
        let
          pkgs = import nixpkgs { inherit system; };
          runtime =
            with pkgs;
            [
              bash
              tmux
              jq
              coreutils
            ]
            # Linux has process command lines in /proc.
            ++ lib.optionals stdenv.hostPlatform.isDarwin [ ps ];
          testTools =
            with pkgs;
            [
              python3
              git
              gnused
              gnugrep
              gawk
              findutils
              # Oh my tmux! finds plugin lines with Perl.
              perl
            ]
            ++ lib.optionals stdenv.hostPlatform.isLinux [ procps ];
          qualityTools = with pkgs; [
            actionlint
            nixfmt
            shellcheck
            shfmt
            ruff
          ];
          packages = {
            inherit (pkgs.callPackage ./packages.nix { })
              tmux-plugin
              claude-plugin
              opencode-plugin
              ;
          };
          # The tests use these in place of the source, which holds every plugin.
          testPlugins = ''
            export TEST_TMUX_PLUGIN=${packages.tmux-plugin}/share/tmux-plugins/tmux-agent-resurrect
            export TEST_CLAUDE_PLUGIN=${packages.claude-plugin}
            export TEST_OPENCODE_PLUGIN=${packages.opencode-plugin}
          '';
          inherit
            (import nixpkgs {
              inherit system;
              config.allowUnfreePredicate = pkg: nixpkgs.lib.getName pkg == "claude-code";
            })
            claude-code
            ;
          scripts = "tmux-agent-resurrect.tmux bin/* lib/*.sh";
          check =
            name: deps: command:
            pkgs.runCommand name { nativeBuildInputs = deps; } ''
              cp -R ${./.} project
              chmod -R u+w project
              cd project
              ${command}
              touch "$out"
            '';
          behavior = ''
            # Darwin's build sandbox cannot execute /usr/bin/env. Patch only
            # disposable test copies; the plugin itself remains portable.
            patchShebangs --build tmux-agent-resurrect.tmux bin
            cp -R ${resurrect} "$TMPDIR/resurrect"
            cp -R ${tpm} "$TMPDIR/tpm"
            chmod -R u+w "$TMPDIR/resurrect" "$TMPDIR/tpm"
            patchShebangs --build "$TMPDIR/resurrect" "$TMPDIR/tpm"
            export RESURRECT_SOURCE="$TMPDIR/resurrect" TPM_SOURCE="$TMPDIR/tpm"
            export OH_MY_TMUX_SOURCE=${oh-my-tmux}
            python3 -m unittest discover -s tests -v -f
          '';
          individualChecks = {
            formatting = check "formatting" qualityTools ''
              nixfmt --check *.nix
              shfmt -d -i 2 -ci ${scripts}
              ruff format --check tests
            '';
            lint = check "lint" (runtime ++ qualityTools) ''
              shellcheck -x ${scripts}
              ruff check tests
              jq -e . .claude-plugin/plugin.json hooks/hooks.json >/dev/null
              actionlint .github/workflows/*.yml
            '';
            behavior = check "behavior" (runtime ++ testTools) behavior;
            packaging = check "packaging" (runtime ++ testTools) ''
              ${testPlugins}
              ${behavior}
            '';
            # Tests with the real harnesses. Claude Code fails to format numbers
            # inside the Darwin sandbox, which nixpkgs also disables to build
            # it there.
            agents =
              (check "agents" (runtime ++ testTools ++ [ claude-code ]) ''
                export HOME="$TMPDIR/home" CLAUDE_CONFIG_DIR="$TMPDIR/claude"
                export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1
                mkdir -p "$HOME"
                claude plugin validate --strict .
                claude plugin validate --strict ${packages.claude-plugin}
                patchShebangs --build tmux-agent-resurrect.tmux bin
                export CLAUDE_BINARY=${pkgs.lib.getExe claude-code}
                export OPENCODE_BINARY=${pkgs.lib.getExe pkgs.opencode}
                python3 -m unittest discover -s tests -v -f -k test_real_
                ${testPlugins}
                python3 -m unittest discover -s tests -v -f -k test_real_
              '').overrideAttrs
                { __noChroot = pkgs.stdenv.hostPlatform.isDarwin; };
            nonflake =
              let
                pinned = import ./default.nix { inherit system; };
                supplied = import ./default.nix { inherit pkgs; };
                drvPaths = pkgs.lib.mapAttrs (_: package: package.drvPath);
              in
              assert pkgs.lib.assertMsg (
                drvPaths pinned == drvPaths packages
              ) "default.nix and the flake must build the same pinned packages";
              assert pkgs.lib.assertMsg (
                drvPaths supplied == drvPaths packages
              ) "default.nix must support a caller-supplied pkgs";
              pkgs.linkFarm "nonflake-packages" (
                pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) pinned
              );
          };
        in
        {
          inherit packages;
          checks = individualChecks // {
            all = pkgs.linkFarm "checks-${system}" (
              pkgs.lib.mapAttrsToList (name: path: { inherit name path; }) individualChecks
            );
          };
          devShells.default = pkgs.mkShell {
            packages =
              runtime
              ++ testTools
              ++ qualityTools
              ++ [
                pkgs.nix
                pkgs.direnv
              ];
            RESURRECT_SOURCE = "${resurrect}";
            TPM_SOURCE = "${tpm}";
            OH_MY_TMUX_SOURCE = "${oh-my-tmux}";
          };
          formatter = pkgs.nixfmt;
        };
    in
    {
      packages = eachSystem (system: (forSystem system).packages);
      checks = eachSystem (system: (forSystem system).checks);
      devShells = eachSystem (system: (forSystem system).devShells);
      formatter = eachSystem (system: (forSystem system).formatter);
    };
}
