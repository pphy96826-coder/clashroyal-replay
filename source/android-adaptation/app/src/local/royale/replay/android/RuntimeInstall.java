package local.royale.replay.android;

import java.io.File;
import java.io.IOException;
import java.util.UUID;

/** Publish a verified private runtime only after extraction has completed. */
final class RuntimeInstall {
    private static void checkedRoot(File root)throws IOException {
        if(!root.getName().matches("(?:python-|android-tools-)[a-f0-9]{16}"))throw new IOException("not a packaged runtime directory");
        File expected=new File(root.getParentFile().getCanonicalFile(),root.getName());
        if(!root.getCanonicalFile().equals(expected))throw new IOException("runtime root is an unexpected link");
    }
    static File quarantineIncomplete(File root)throws IOException {
        checkedRoot(root);
        if(!root.isDirectory()||new File(root,"runtime-files.json").exists())throw new IOException("runtime is not an interrupted extraction");
        File saved=new File(root.getParentFile(),root.getName()+".incomplete."+UUID.randomUUID());
        if(!root.renameTo(saved))throw new IOException("cannot preserve interrupted runtime");
        return saved;
    }
    static File createStaging(File root)throws IOException {
        checkedRoot(root);
        if(root.exists())throw new IOException("runtime already published");
        File staged=new File(root.getParentFile(),root.getName()+".installing."+UUID.randomUUID());
        if(!staged.mkdir())throw new IOException("cannot create private runtime staging");
        return staged;
    }
    static void publish(File staged,File root)throws IOException {
        checkedRoot(root);
        if(!staged.getCanonicalFile().getParentFile().equals(root.getParentFile().getCanonicalFile())
            ||!staged.getName().startsWith(root.getName()+".installing.")
            ||!staged.getCanonicalFile().equals(new File(root.getParentFile().getCanonicalFile(),staged.getName()))
            ||!new File(staged,"runtime-files.json").isFile()||root.exists())throw new IOException("runtime staging is not publishable");
        if(!staged.renameTo(root))throw new IOException("cannot publish verified runtime");
    }
}
