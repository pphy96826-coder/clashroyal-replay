import java.nio.file.*;
import java.nio.charset.StandardCharsets;
import local.royale.replay.android.ReplaySource;

/** Host-side parity check against the authoritative desktop parser. */
public final class SourceCheck {
    public static void main(String[] args)throws Exception {
        ReplaySource.Info info=ReplaySource.parse(new String(Files.readAllBytes(Paths.get(args[0])),StandardCharsets.UTF_8));
        System.out.println("{\"tag\":\""+info.tag+"\",\"events\":"+info.count()+",\"plays\":"+info.plays+",\"abilities\":"+info.abilities+",\"first_tick\":"+info.firstTick+",\"last_tick\":"+info.lastTick+",\"orientation\":"+info.orientation+"}");
    }
}
