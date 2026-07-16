{
  description = "Reverse-engineering workbench for 8BitDo Ultimate 2C controller + 2.4GHz dongle firmware (Telink TC32). Pins the vendor firmware images as fixed-output derivations, extracts the ebitdo payloads, and provides Ghidra with the TC32 processor module plus supporting tools. Standalone; not consumed by the parent flake.";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-26.05";
    flake-utils.url = "github:numtide/flake-utils";
    tc32-ghidra = {
      url = "github:trust1995/Ghidra_TELink_TC32/f466dac5f746ac65d57dbbf8eb534988e1076f53";
      flake = false;
    };
  };

  outputs = { self, nixpkgs, flake-utils, tc32-ghidra }:
    flake-utils.lib.eachSystem [ "x86_64-linux" ] (system:
      let
        pkgs = import nixpkgs { inherit system; };
        lib = nixpkgs.lib;

        base = "http://dl.8bitdo.com:8080";
        upload = "${base}/firmwareFile/upload";

        # dl.8bitdo.com API types: 75 controller, 76 dongle, 77 wired. Verify downloads by size; the manifest md5 field is unreliable.
        specs = {
          "ctrl-v109" = { url = "${upload}/3652c29e-7b6c-4521-9426-abf153e7298b.dat"; hash = "sha256-hzSeYDu5LWrp/23vtvMrEN4vLTJS/k5EL6eZP5gvKlo="; };
          "ctrl-v106" = { url = "${upload}/eeaedee4-deda-481a-aede-63e73a6eb1c0.dat"; hash = "sha256-9/iwKd3yY4mIVr6ES/017lG3sxlWzOha71OGOnwP+M4="; };
          "dongle-v103" = { url = "${upload}/8c7285c9-e169-4f22-8e3b-928d08599151.dat"; hash = "sha256-5t0lZeIA5kfkeYL0LriOyumdNKseGrIBi0mizl+Rodk="; };
          "dongle-v100" = { url = "${upload}/4e47d5a0-0776-444c-a9fe-2a3a0a08d5d6.dat"; hash = "sha256-oqH5wjw9kGiAA7po193U/p06rRseRAITKV5DVOcfdW0="; };
        };

        firmware = lib.mapAttrs
          (n: s: pkgs.fetchurl { name = "8bitdo-2c-${n}.dat"; inherit (s) url hash; })
          specs;

        # ebitdo container = 28-byte header + raw Telink image. Strip to the flashed payload; load base is 0x6000.
        payloads = lib.mapAttrs
          (n: fw: pkgs.runCommand "8bitdo-2c-${n}-payload.bin" { } ''tail -c +29 ${fw} > $out'')
          firmware;

        loadBase = "0x6000"; # img address of payload offset 0

        # Assemble a shim .s (sections placed at the img addresses in `place`, firmware `syms` resolved) into one raw .bin per section.
        mkAsm = { src, syms ? { }, place }: pkgs.runCommand "8bitdo-2c-shim"
          { nativeBuildInputs = [ tc32-tools ]; }
          ''
            cat > shim.ld <<'LD'
            ${lib.concatStrings (lib.mapAttrsToList (n: v: "${n} = ${v};\n") syms)}SECTIONS {
            ${lib.concatStrings (lib.mapAttrsToList (sec: p: "  ${sec} ${p.addr} : { *(${sec}) }\n") place)}}
            LD
            tc32-elf-as ${src} -o shim.o
            tc32-elf-ld -T shim.ld shim.o -o shim.elf
            mkdir -p $out
            ${lib.concatStrings (lib.mapAttrsToList (sec: p: "tc32-elf-objcopy -O binary --only-section=${sec} shim.elf $out/${lib.removePrefix "." sec}.bin\n") place)}
          '';

        # Modded firmware whose code comes from an assembled shim: each `place` section is written at its img address (apply.py maps it to a file offset via --load-base), asserting the stock bytes in `old`. Extra `patches` (data/string .py) apply after.
        mkAsmMod = modname: base: { src, syms ? { }, place, patches ? [ ] }:
          let
            asm = mkAsm { inherit src syms place; };
            placeArgs = lib.concatStringsSep " " (lib.mapAttrsToList
              (sec: p: "--place ${p.addr}:${p.old}:${asm}/${lib.removePrefix "." sec}.bin")
              place);
          in
          pkgs.runCommand "8bitdo-2c-${modname}.bin" { nativeBuildInputs = [ pkgs.python3 ]; }
            ''python3 ${./patches/apply.py} ${base} $out --load-base ${loadBase} ${placeArgs} ${lib.concatStringsSep " " (map (p: "${p}") patches)}'';

        mods = {
          # Controller: fold battery 0-100 into the spare button-word bits; rebrand Ultima+e.
          "battery-ctrl-v109" = mkAsmMod "battery-ctrl-v109" payloads."ctrl-v109" {
            src = ./patches/battery-ctrl.s;
            syms = { battery = "0x842e04"; button_word = "0x84342c"; };
            place = {
              ".tramp" = { addr = "0xc8f0"; old = "11080450"; };
              ".shim" = { addr = "0x18280"; old = lib.concatStrings (lib.replicate 40 "00"); };
            };
            patches = [ ./patches/brand.py ];
          };
          # Dongle: relay battery -> report[18], L4/R4/Square -> report[19]. No rebrand — the dongle's product strings sit above its 0x7000 app-IAP write window, so a brand patch there is never flashed.
          "batt-l4r4-dongle-v103" = mkAsmMod "batt-l4r4-dongle-v103" payloads."dongle-v103" {
            src = ./patches/batt-l4r4-dongle.s;
            place = {
              ".tramp" = { addr = "0x74be"; old = "10a3b344"; };
              ".shim" = { addr = "0x8350"; old = lib.concatStrings (lib.replicate 24 "00"); };
            };
          };
        };

        # A Ghidra module root holding only the TC32 processor, SLEIGH precompiled so nothing writes to the store at load. Ghidra 12 discovers it via NIX_GHIDRAHOME (an extra application root added by the nixpkgs patch), not by scanning the install's Processors dir.
        tc32-module = pkgs.stdenv.mkDerivation {
          pname = "ghidra-tc32-module";
          inherit (pkgs.ghidra) version;
          dontUnpack = true;
          buildPhase = ''
            runHook preBuild
            export HOME=$TMPDIR
            install -d Processors/Telink_TC32
            cp -a ${tc32-ghidra}/Telink_TC32/. Processors/Telink_TC32/
            chmod -R u+w Processors/Telink_TC32
            ${pkgs.ghidra}/lib/ghidra/support/sleigh -a Processors/Telink_TC32
            runHook postBuild
          '';
          installPhase = ''
            runHook preInstall
            install -d $out/lib/ghidra/Ghidra
            cp -a Processors $out/lib/ghidra/Ghidra/Processors
            runHook postInstall
          '';
        };

        ghidra-tc32 = pkgs.symlinkJoin {
          name = "ghidra-tc32-${pkgs.ghidra.version}";
          paths = [ tc32-module ];
          nativeBuildInputs = [ pkgs.makeBinaryWrapper ];
          postBuild = ''
            touch $out/lib/ghidra/Ghidra/.dbDirLock
            makeWrapper ${pkgs.ghidra}/bin/ghidra $out/bin/ghidra \
              --set NIX_GHIDRAHOME "$out/lib/ghidra/Ghidra"
            makeWrapper ${pkgs.ghidra}/bin/ghidra-analyzeHeadless $out/bin/ghidra-analyzeHeadless \
              --set NIX_GHIDRAHOME "$out/lib/ghidra/Ghidra"
            ln -s ${pkgs.ghidra}/share $out/share
          '';
          meta.description = "Ghidra with the Telink TC32 processor module (SLEIGH precompiled), added via NIX_GHIDRAHOME";
        };

        refetch-firmware = pkgs.writeShellApplication {
          name = "refetch-firmware";
          runtimeInputs = [ pkgs.curl pkgs.jq ];
          text = ''
            type=''${1:?usage: refetch-firmware <type> [outfile]  (75=ctrl 76=dongle 77=wired)}
            out=''${2:-firmware-type''${type}.dat}
            api=http://dl.8bitdo.com:8080
            path=$(curl -sS -X POST -H "Type: ''${type}" "''${api}/firmware/select" | jq -r '.list[0].filePathName')
            if [ -z "''${path}" ] || [ "''${path}" = null ]; then
              echo "no firmware for type ''${type}" >&2
              exit 1
            fi
            curl -sS -o "''${out}" "''${api}''${path}"
            echo "wrote ''${out} ($(stat -c%s "''${out}") bytes)"
          '';
        };

        # Unified flasher: app IAP (0x8105) for ctrl/dongle + bootloader (0x3208) address protocol, selected by --target.
        flash-2c = pkgs.writeShellApplication {
          name = "flash-2c";
          runtimeInputs = [ (pkgs.python3.withPackages (p: [ p.pyusb ])) ];
          text = ''
            export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.libusb1 ]}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            exec python3 ${./flasher/flash2c.py} "$@"
          '';
        };

        # Flashes every plugged-in device with the two production mods baked in as payloads.
        update-all = pkgs.writeShellApplication {
          name = "update-all";
          runtimeInputs = [ (pkgs.python3.withPackages (p: [ p.pyusb ])) ];
          text = ''
            export LD_LIBRARY_PATH="${lib.makeLibraryPath [ pkgs.libusb1 ]}''${LD_LIBRARY_PATH:+:$LD_LIBRARY_PATH}"
            exec python3 ${./flasher/flash2c.py} update-all \
              --ctrl-payload ${mods."battery-ctrl-v109"} \
              --dongle-payload ${mods."batt-l4r4-dongle-v103"} "$@"
          '';
        };

        # gen must reproduce the captured vendor command stream byte-for-byte from the stock payload.
        mkTemplateCheck = target: payload: tmpl:
          pkgs.runCommand "flash-template-${target}"
            { nativeBuildInputs = [ (pkgs.python3.withPackages (p: [ p.pyusb ])) ]; }
            ''
              python3 ${./flasher/flash2c.py} --target ${target} gen ${payload} --template ${tmpl}
              touch $out
            '';

        # Telink's own TC32 binutils (GCC 4.5.1 tc32-elf, x86-64), patchelf'd for nix. Assembles shim source into raw bytes for the patches.
        tc32-tools =
          let
            rev = "8ec375bb95ef63b6d0a4b18008913c03e7928710";
            tool = name: hash: pkgs.fetchurl {
              url = "https://raw.githubusercontent.com/flyskywhy/tc32/${rev}/bin/tc32-elf-${name}";
              inherit hash;
            };
          in
          pkgs.runCommand "tc32-tools" { nativeBuildInputs = [ pkgs.patchelf ]; } ''
            mkdir -p $out/bin
            install -m0755 ${tool "as" "sha256-R4fR5u4ShEOaRwypu5gC3YkvLYaldbw4zm/9XMUs5OE="} $out/bin/tc32-elf-as
            install -m0755 ${tool "ld" "sha256-alEF9IuYI6FEdFnctty3Szk8W8SIRlfuFiEECSQ1mLM="} $out/bin/tc32-elf-ld
            install -m0755 ${tool "objcopy" "sha256-xa8ZUzRV+6XyOxveznOvRhITqQrJLW2xJQFz1XQoOps="} $out/bin/tc32-elf-objcopy
            install -m0755 ${tool "objdump" "sha256-j1x4eaMrgkdXFNnO+Pv3v5TYpoWzd8o8B9yfYZNxP48="} $out/bin/tc32-elf-objdump
            for f in $out/bin/*; do
              patchelf --set-interpreter "$(cat ${pkgs.stdenv.cc}/nix-support/dynamic-linker)" \
                --set-rpath "${lib.makeLibraryPath [ pkgs.zlib pkgs.glibc ]}" "$f"
            done
          '';

      in
      {
        packages =
          (lib.mapAttrs' (n: v: lib.nameValuePair "fw-${n}" v) firmware) //
          (lib.mapAttrs' (n: v: lib.nameValuePair "payload-${n}" v) payloads) //
          (lib.mapAttrs' (n: v: lib.nameValuePair "mod-${n}" v) mods) //
          {
            inherit ghidra-tc32 refetch-firmware flash-2c update-all tc32-tools;
            default = ghidra-tc32;
          };

        checks = {
          flash-template-ctrl = mkTemplateCheck "ctrl" payloads."ctrl-v109" ./test/ctrl-v109-flash.tmpl;
          flash-template-dongle = mkTemplateCheck "dongle" payloads."dongle-v103" ./test/dongle-v103-flash.tmpl;
        };

        devShells.default = pkgs.mkShell {
          packages = [
            ghidra-tc32
            refetch-firmware
            pkgs.python3
            pkgs.rizin
            pkgs.binwalk
            pkgs.binutils
            pkgs.file
            pkgs.ripgrep
            pkgs.jq
            pkgs.curl
          ];
          shellHook = ''
            echo "8bitdo-2c-re devshell — ghidra (Telink_TC32), rizin, binwalk, refetch-firmware"
            echo "  payloads:  nix build .#payload-ctrl-v109 .#payload-dongle-v103"
            echo "  firmware:  nix build .#fw-ctrl-v109   (raw .dat, header intact)"
          '';
        };
      });
}
