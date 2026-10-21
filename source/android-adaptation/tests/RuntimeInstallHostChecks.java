package local.royale.replay.android;
import java.io.*;
import java.nio.file.*;

public final class RuntimeInstallHostChecks {
    static int checks;
    static void yes(boolean value){if(!value)throw new AssertionError("runtime publication failed");++checks;}
    interface Action{void run()throws Exception;}
    static void rejected(Action action)throws Exception {try{action.run();throw new AssertionError("unexpected publication");}catch(IOException expected){++checks;}}
    public static void main(String[] args)throws Exception {
        File parent=Files.createTempDirectory("runtime install ").toFile();
        File root=new File(parent,"python-0123456789abcdef");root.mkdir();
        Files.write(new File(root,"partial.bin").toPath(),new byte[]{3,1,4});
        File saved=RuntimeInstall.quarantineIncomplete(root);
        yes(!root.exists());yes(Files.readAllBytes(new File(saved,"partial.bin").toPath())[2]==4);
        File staged=RuntimeInstall.createStaging(root);yes(!root.exists());yes(staged.isDirectory());
        rejected(()->RuntimeInstall.publish(staged,root));
        Files.write(new File(staged,"runtime-files.json").toPath(),"{}".getBytes("UTF-8"));
        Files.write(new File(staged,"payload").toPath(),new byte[]{9});RuntimeInstall.publish(staged,root);
        yes(root.isDirectory()&&!staged.exists());yes(new File(root,"payload").length()==1);
        rejected(()->RuntimeInstall.quarantineIncomplete(root));rejected(()->RuntimeInstall.createStaging(root));
        rejected(()->RuntimeInstall.quarantineIncomplete(new File(parent,"user-replays")));
        System.out.println("PASS "+checks+" runtime interrupted-extraction/publication checks");
    }
}
