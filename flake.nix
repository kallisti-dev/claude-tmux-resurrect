{
  description = "Exact, deferred Claude Code session restoration for tmux-resurrect";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixpkgs-unstable";
    home-manager = {
      url = "github:nix-community/home-manager";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    nix-darwin = {
      url = "github:nix-darwin/nix-darwin";
      inputs.nixpkgs.follows = "nixpkgs";
    };
    resurrect = {
      url = "github:tmux-plugins/tmux-resurrect";
      flake = false;
    };
  };

  outputs =
    {
      nixpkgs,
      home-manager,
      nix-darwin,
      resurrect,
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
          runtime = with pkgs; [
            bash
            tmux
            jq
            coreutils
          ];
          testTools =
            with pkgs;
            [
              python3
              git
              gnumake
              gnused
              gnugrep
              gawk
              findutils
            ]
            ++ lib.optionals stdenv.hostPlatform.isLinux [ procps ];
          qualityTools = with pkgs; [
            actionlint
            nixfmt
            shellcheck
            shfmt
            ruff
          ];
          package = pkgs.callPackage ./package.nix { };
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
            # disposable test copies; the normal installation remains portable.
            export INSTALL_SOURCE=${./.}
            patchShebangs --build bin
            cp -R ${resurrect} "$TMPDIR/resurrect"
            chmod -R u+w "$TMPDIR/resurrect"
            patchShebangs --build "$TMPDIR/resurrect"
            export RESURRECT_SOURCE="$TMPDIR/resurrect"
            python3 -m unittest discover -s tests -v -f
          '';
          individualChecks = {
            formatting = check "formatting" qualityTools ''
              nixfmt --check *.nix nix/*.nix tests/*.nix
              shfmt -d -i 2 -ci bin/* share/claude-tmux-resurrect/lib.sh
              ruff format --check tests
            '';
            lint = check "lint" (runtime ++ qualityTools) ''
              shellcheck -x bin/* share/claude-tmux-resurrect/lib.sh
              ruff check tests
              jq -e . examples/claude-hooks.json >/dev/null
              actionlint .github/workflows/*.yml
            '';
            behavior = check "behavior" (runtime ++ testTools) behavior;
            packaging = check "packaging" (runtime ++ testTools) ''
              export PROJECT_BIN=${package}/bin
              ${behavior}
            '';
            modules = import ./tests/modules.nix {
              inherit
                pkgs
                home-manager
                nixpkgs
                package
                ;
              module = ./nix/home-manager.nix;
            };
            nixos-module = import ./tests/nixos-module.nix {
              inherit pkgs nixpkgs package;
              module = ./nix/nixos.nix;
            };
            darwin-module = import ./tests/darwin-module.nix {
              inherit
                pkgs
                nixpkgs
                nix-darwin
                package
                ;
              module = ./nix/darwin.nix;
            };
            nonflake =
              let
                pinnedPackage = import ./default.nix { inherit system; };
                suppliedPackage = import ./default.nix { inherit pkgs; };
              in
              assert pkgs.lib.assertMsg (
                pinnedPackage.drvPath == package.drvPath
              ) "default.nix and the flake must build the same pinned package";
              assert pkgs.lib.assertMsg (
                suppliedPackage.drvPath == package.drvPath
              ) "default.nix must support a caller-supplied pkgs";
              pkgs.linkFarm "nonflake-package" [
                {
                  name = "package";
                  path = pinnedPackage;
                }
              ];
          };
        in
        {
          packages = {
            default = package;
            claude-tmux-resurrect = package;
          };
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
          };
          formatter = pkgs.nixfmt;
        };
    in
    {
      homeManagerModules.default = ./nix/home-manager.nix;
      nixosModules.default = ./nix/nixos.nix;
      darwinModules.default = ./nix/darwin.nix;
      packages = eachSystem (system: (forSystem system).packages);
      checks = eachSystem (system: (forSystem system).checks);
      devShells = eachSystem (system: (forSystem system).devShells);
      formatter = eachSystem (system: (forSystem system).formatter);
    };
}
