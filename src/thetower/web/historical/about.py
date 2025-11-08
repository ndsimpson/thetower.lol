import streamlit as st


def compute_about(*args, **kwargs):
    st.title("About")
    st.markdown("This project is primarily managed by `thedisasterfish`, in collaboration with the Discord and Reddit moderation teams.")
    st.markdown("Site orignally created by `098799` ('this guy' on discord) 2022-2024.")
    st.markdown("Special thanks to these people, in no particular order: `_xskye_`, `andreasjn`, `Jim808`, `ObsUK`, `Bartek`, `Milamber33`, `Fnord`, and `Neothin87`.")
    st.write(
        "DISCLAIMER:  All work is best effort and strictly voluntary.  Inclusion in the results isn't guaranteed and we make no warranties as to the site accuracy."
    )


compute_about()
