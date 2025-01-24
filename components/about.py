import streamlit as st


def compute_about(*args, **kwargs):
    st.title("About")
    st.markdown("Currenly ran by the discord team.  Primary contact: `thedisasterfish`")
    st.markdown("Site orignally created by `098799` ('this guy' on discord) 2022-2024.")
    st.markdown("Thanks to `andreasjn` for the help with the discord bot.")
    st.markdown("Thanks to `Milamber33` for a lot of help with css and other things.")
    st.markdown("Thanks to `Jim808`, `ObsUK` and `Bartek` for a graph ideas and encouragement.")
    st.markdown("Thanks to `Fnord`, `Neothin87`, and others for the encouragement and ideas")
    st.markdown("Thanks to `Pog` and the discord mods for all the work on sus reports.")

    st.write("If you have any questions of concerns regarding privacy, including opt outs, please contact fish@thetower.lol.")

    st.write("DISCLAIMER:  This is a community run project.  All work is best effort and strictly voluntary.  Inclusion in the results isn't guaranteed and we make no warranties as to the site accuracy.")


compute_about()
