package local.royale.replay.android;

import android.app.Activity;
import android.content.Context;
import android.content.Intent;
import android.net.Uri;
import android.provider.Settings;

/** Requests the system's per-app overlay screen; never grants via root/appops. */
final class OverlayAccess {
    static boolean allowed(Context context){return Settings.canDrawOverlays(context);}
    static boolean ensure(Activity activity){
        if(allowed(activity))return true;
        activity.startActivity(new Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION).setData(Uri.parse("package:local.royale.replay.android")));
        return false;
    }
    private OverlayAccess(){}
}
