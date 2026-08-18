import subprocess
from pathlib import Path


def build_ffmpeg_concat_command(clip_paths: list[str], output_path: str) -> list[str]:
    if not clip_paths:
        raise ValueError("clip_paths must not be empty")
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    return [
        "ffmpeg",
        "-y",
        "-f", "concat",
        "-safe", "0",
        "-i", concat_list_path,
        "-c", "copy",
        output_path,
    ]


def write_concat_list(clip_paths: list[str], concat_list_path: str) -> None:
    # ffmpeg's concat demuxer resolves relative file paths against the concat
    # list's own directory, not the process's cwd -- writing absolute paths
    # avoids that mismatch (e.g. a clip at "media/x/y.mp4" listed from a
    # concat file that itself lives under "media/" would otherwise resolve
    # to "media/media/x/y.mp4").
    with open(concat_list_path, "w", encoding="utf-8") as f:
        for path in clip_paths:
            absolute_path = Path(path).resolve().as_posix()
            f.write(f"file '{absolute_path}'\n")


def assemble(clip_paths: list[str], output_path: str) -> str:
    Path(output_path).parent.mkdir(parents=True, exist_ok=True)
    concat_list_path = str(Path(output_path).with_suffix(".txt"))
    write_concat_list(clip_paths, concat_list_path)
    command = build_ffmpeg_concat_command(clip_paths, output_path)
    subprocess.run(command, check=True)
    return output_path
